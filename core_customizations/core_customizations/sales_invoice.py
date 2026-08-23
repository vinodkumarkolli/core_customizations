# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def validate_delivery_note_mandatory(doc, method=None):
	"""
	Enforces 3PL dispatch-first dependency:
	A standard Sales Invoice cannot be created/saved without linking to at least one Delivery Note.
	(Excludes Return / Credit Notes and POS Invoices).
	"""
	if doc.is_return or getattr(doc, "is_pos", 0):
		return

	# Check if any item row has a linked Delivery Note
	has_delivery_note = False
	for item in doc.get("items", []):
		if getattr(item, "delivery_note", None):
			has_delivery_note = True
			break

	if not has_delivery_note:
		frappe.throw(
			_("Delivery Note is mandatory for creating a Sales Invoice. Please generate the Delivery Note from the Sales Order first, complete dispatch & packing, and create the invoice from the Delivery Note."),
			title=_("Delivery Note Required")
		)
