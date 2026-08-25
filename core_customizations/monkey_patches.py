# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt
"""
Monkey patch to override stock update functionality for Delivery Note, POS Invoice, and Sales Invoice.

This patch adds batch-based pricing and serial number filtering for stock updates.
"""

import erpnext.stock.get_item_details
import frappe
from erpnext.stock.get_item_details import (
	filter_batches,
	get_batch_based_item_price,
	get_filtered_serial_nos,
	has_incorrect_serial_nos,
)
from frappe.utils import cint


def custom_update_stock(ctx, out, doc=None):
	"""
	Custom stock update function for Delivery Note, POS Invoice, and Sales Invoice.

	Args:
	        ctx (dict): Context containing doctype, item_code, warehouse, and other transaction details.
	        out (dict): Output dictionary to be updated with batch_no, rate, serial_no etc.
	        doc (Document, optional): Frappe document object for the transaction.

	Returns:
	        None: Modifies 'out' dictionary in place.
	"""
	from erpnext.stock.doctype.batch.batch import get_available_batches
	from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos_for_outward

	if (
		(
			ctx.get("doctype") in ["Delivery Note", "POS Invoice"]
			or (ctx.get("doctype") == "Sales Invoice" and ctx.get("update_stock"))
		)
		and out.warehouse
		and out.stock_qty > 0
	):
		if doc and isinstance(doc, dict):
			doc = frappe._dict(doc)

		kwargs = frappe._dict(
			{
				"item_code": ctx.item_code,
				"warehouse": ctx.warehouse,
				"based_on": frappe.get_single_value("Stock Settings", "pick_serial_and_batch_based_on"),
				"sabb_voucher_no": doc.get("name") if doc else None,
				"sabb_voucher_detail_no": ctx.child_docname,
				"sabb_voucher_type": ctx.doctype,
				"pick_reserved_items": True,
				"qty": out.stock_qty,
			}
		)

		if ctx.get("doctype") == "Delivery Note":
			kwargs["against_sales_order"] = ctx.get("against_sales_order")

		if ctx.get("ignore_serial_nos"):
			kwargs["ignore_serial_nos"] = ctx.get("ignore_serial_nos")

		qty = out.stock_qty
		batches = []
		if out.has_batch_no and not ctx.get("batch_no"):
			batches = get_available_batches(kwargs)
			if doc:
				filter_batches(batches, doc)

			for batch_no, batch_qty in batches.items():
				# Fix: Handle doc being None
				price_list = doc.get("selling_price_list") if doc else ctx.get("price_list")
				rate = get_batch_based_item_price(
					{"price_list": price_list, "uom": out.uom, "batch_no": batch_no},
					out.item_code,
				)
				if batch_qty >= qty:
					out.update({"batch_no": batch_no, "actual_batch_qty": qty})
					if rate:
						out.update({"rate": rate, "price_list_rate": rate})
					break
				else:
					qty -= batch_qty

				out.update({"batch_no": batch_no, "actual_batch_qty": batch_qty})
				if rate:
					out.update({"rate": rate, "price_list_rate": rate})

		if out.has_serial_no and out.has_batch_no and has_incorrect_serial_nos(ctx, out):
			kwargs["batches"] = [ctx.get("batch_no")] if ctx.get("batch_no") else [out.get("batch_no")]
			serial_nos = get_serial_nos_for_outward(kwargs)
			if doc:
				serial_nos = get_filtered_serial_nos(serial_nos, doc)

			out["serial_no"] = "\n".join(serial_nos[: cint(out.stock_qty)])

		elif out.has_serial_no and not ctx.get("serial_no"):
			serial_nos = get_serial_nos_for_outward(kwargs)
			if doc:
				serial_nos = get_filtered_serial_nos(serial_nos, doc)

			out["serial_no"] = "\n".join(serial_nos[: cint(out.stock_qty)])


# Apply the patch
erpnext.stock.get_item_details.update_stock = custom_update_stock


def custom_validate_delivery_note(self):
	"""
	Allow packing slips for Draft (0) and Submitted (1) Delivery Notes,
	blocking only Cancelled (2) Delivery Notes.
	"""
	if not self.delivery_note:
		frappe.throw(frappe._("Delivery Note is mandatory."))

	dn_docstatus = frappe.db.get_value("Delivery Note", self.delivery_note, "docstatus")
	if dn_docstatus == 2:
		frappe.throw(frappe._("Cannot create or modify a Packing Slip for a Cancelled Delivery Note."))


def custom_validate_items(self):
	"""
	Validates that packed items link to an active Delivery Note Item (docstatus < 2).
	"""
	for item in self.items:
		if not item.dn_detail or not frappe.db.exists(
			"Delivery Note Item",
			{"name": item.dn_detail, "parent": self.delivery_note, "docstatus": ["<", 2]},
		):
			if not frappe.db.exists(
				"Packed Item",
				{"name": item.dn_detail, "parent": self.delivery_note, "docstatus": ["<", 2]},
			):
				frappe.throw(
					frappe._(
						"Row {0}: Please provide a valid Delivery Note Item or Packed Item reference."
					).format(item.idx)
				)


try:
	import erpnext.stock.doctype.packing_slip.packing_slip as ps_module

	ps_module.PackingSlip.validate_delivery_note = custom_validate_delivery_note
	ps_module.PackingSlip.validate_items = custom_validate_items
except Exception:
	pass
