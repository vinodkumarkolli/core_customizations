# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""
	1. Remove deprecated Sales Invoice custom transporter fields from the database.
	2. Remove obsolete Print Formats (Courier Slip, Dummy Bill).
	"""
	fields_to_remove = [
		"Sales Invoice-custom_transporter_section",
		"Sales Invoice-custom_transporter",
		"Sales Invoice-custom_transporter_from_address",
		"Sales Invoice-custom_transporter_from_address_display",
		"Sales Invoice-custom_is_godown_delivery",
		"Sales Invoice-custom_transporter_col_break",
		"Sales Invoice-custom_transporter_to_address",
		"Sales Invoice-custom_transporter_to_address_display",
	]

	for fname in fields_to_remove:
		if frappe.db.exists("Custom Field", fname):
			frappe.delete_doc("Custom Field", fname, ignore_permissions=True)

	pfs_to_remove = [
		"Courier Slip",
		"Dummy Bill",
	]

	for pf in pfs_to_remove:
		if frappe.db.exists("Print Format", pf):
			frappe.delete_doc("Print Format", pf, ignore_permissions=True)

	frappe.db.commit()
