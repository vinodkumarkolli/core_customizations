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


try:
	import crm.fcrm.doctype.crm_call_log.crm_call_log as crm_call_log_module

	_original_get_reference_contact = crm_call_log_module.get_reference_contact

	def sarvam_get_contact_by_phone_number(phone_number):
		# Imported lazily, not at module load time: this file runs from
		# core_customizations/__init__.py, so importing a sibling submodule
		# of the same still-loading package here deadlocks the circular
		# import instead of resolving it.
		from core_customizations.core_customizations.sarvam_telephony import (
			get_contact_by_phone_number,
		)

		return get_contact_by_phone_number(phone_number)

	def get_issue_contact(name):
		"""
		Business Purpose: [BR-TEL-001] Labels a Support-ticket call-log entry
		with the ticket's contact (falling back to the ticket subject), so it
		reads the same way a CRM Lead/Deal reference does.

		Args:
			name (str): Name of the Issue.

		Returns:
			dict | None: {"full_name": ..., "image": ...}, or None if the
			Issue no longer exists.
		"""
		issue = frappe.db.get_value("Issue", name, ["subject", "contact"], as_dict=True)
		if not issue:
			return None

		full_name, image = issue.subject, None
		if issue.contact:
			contact = frappe.db.get_value(
				"Contact", issue.contact, ["full_name", "image"], as_dict=True
			)
			if contact and contact.full_name:
				full_name, image = contact.full_name, contact.image

		return {"full_name": full_name, "image": image}

	def custom_get_call_contact(call, phone_number):
		"""
		Business Purpose: [BR-TEL-001] Extends CRM's call-log contact
		resolution - used by both the call-log drawer and the CRM activity
		timeline (`crm.api.activities`) - to recognise an `Issue` reference,
		and to fall back to the Sarvam-aware phone lookup instead of CRM's
		bare one so even an unlinked call surfaces an open Support ticket.

		Args:
			call (dict): Parsed call log row with reference_doctype/docname.
			phone_number (str): Caller/callee number used as a fallback lookup.

		Returns:
			dict: {"full_name": ..., "image": ...}, or {} when not permitted.
		"""
		doctype, name = call.get("reference_doctype"), call.get("reference_docname")

		# @businessRule [BR-TEL-001] An explicit Issue reference on the call
		# itself takes priority over a fresh phone-number lookup.
		if doctype == "Issue" and name:
			if not frappe.has_permission("Issue", "read", name):
				return {}
			return get_issue_contact(name) or {}

		if doctype not in ("CRM Lead", "CRM Deal") or not name:
			return sarvam_get_contact_by_phone_number(phone_number)

		if not frappe.has_permission(doctype, "read", name):
			return {}

		return _original_get_reference_contact(doctype, name) or {}

	crm_call_log_module.get_call_contact = custom_get_call_contact
except Exception:
	pass
