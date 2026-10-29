# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt
"""
Monkey patches for Packing Slip validation.

Batch-based pricing and serial number picking are native in ERPNext v16, so update_stock is no longer overridden.
"""

import frappe


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
