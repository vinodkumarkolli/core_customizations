# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def validate_delivery_note_mandatory(doc, method=None):
	"""
	Enforces 3PL dispatch-first dependency:
	1. A standard Sales Invoice cannot be created/saved without linking to at least one Delivery Note.
	2. update_stock must not be enabled on the Sales Invoice because stock movement & batch allocation
	   are handled by the upstream Delivery Note.
	(Excludes Return / Credit Notes, POS Invoices, Consolidated POS Invoices, and POS Profile invoices).

	Business Purpose: Enforces the dispatch-first flow (Epic 1) to ensure wholesale orders are fully packed before billing.
	"""
	if (
		doc.is_return
		or getattr(doc, "is_pos", 0)
		or getattr(doc, "is_consolidated", 0)
		or getattr(doc, "pos_profile", None)
	):
		return

	# @businessRule [BR-SALES-001] Wholesale Dispatch-First Flow
	# Check if any item row is linked to a POS Invoice or Delivery Note
	has_delivery_note = False
	for item in doc.get("items", []):
		if getattr(item, "pos_invoice", None) or getattr(item, "pos_invoice_item", None):
			return
		if getattr(item, "delivery_note", None):
			has_delivery_note = True

			break

	if not has_delivery_note:
		frappe.throw(
			_(
				"Delivery Note is mandatory for creating a Sales Invoice. Please generate the Delivery Note from the Sales Order first, complete dispatch & packing, and create the invoice from the Delivery Note."
			),
			title=_("Delivery Note Required"),
		)

	# @businessRule [BR-SALES-001] Wholesale Dispatch-First Flow
	# The subsequent Sales Invoice must not update stock
	if getattr(doc, "update_stock", 0):
		frappe.throw(
			_(
				"Update Stock cannot be enabled on a Sales Invoice created from a Delivery Note. Stock movement and batch allocation are already handled by the Delivery Note."
			),
			title=_("Invalid Stock Update"),
		)
