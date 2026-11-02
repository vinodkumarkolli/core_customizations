import frappe
from frappe import _


def guard_duplicate_mobile(doc, method=None):
	"""
	Business Purpose: [BR-CRM-001] Refuses to create a second CRM Lead for a
	mobile number that already has one, on the server - so duplicates are
	prevented regardless of what creates the Lead (Desk UI, Data Import, the
	CRM frontend, or an external caller like the Sarvam voice agent's
	lead-creation tool), not just the ones that happen to check first.

	Runs on `validate`, after `phone_normalise.normalise_lead`'s
	`before_validate` hook, so `mobile_no` is already in canonical +91 form
	before being checked - two spellings of the same number can't slip past
	as "different".

	Args:
		doc (CRM Lead): The Lead being saved.
		method (str | None): Unused; required by Frappe's doc_event signature.

	Raises:
		frappe.DuplicateEntryError: If this is a new Lead and another CRM
			Lead already has the same `mobile_no`.
	"""
	if not doc.is_new() or not doc.mobile_no:
		return

	existing = frappe.db.get_value("CRM Lead", {"mobile_no": doc.mobile_no}, "name")
	if existing:
		frappe.throw(
			_("A CRM Lead already exists for {0}: {1}").format(doc.mobile_no, existing),
			frappe.DuplicateEntryError,
		)
