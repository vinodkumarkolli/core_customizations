import frappe

# @businessRule [BR-CRM-001] The Sarvam "Sravi Enterprises Customer Care"
# inbound agent (app_id Conversatio-5959ebd0-3da4) parses this exact message
# to decide what to tell a repeat caller - a fixed "DUPLICATE_LEAD:" token
# followed by semicolon-separated key=value pairs, never translated or
# reworded. Changing the token or the field set is a breaking change for
# that agent's prompt, not just a copy edit.
DUPLICATE_LEAD_MESSAGE = "DUPLICATE_LEAD: name={name}; lead_name={lead_name}; mobile_no={mobile_no}; status={status}"


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

	The refusal message is a fixed `DUPLICATE_LEAD: ...` token, not a
	human-facing sentence - see `DUPLICATE_LEAD_MESSAGE`.

	Args:
		doc (CRM Lead): The Lead being saved.
		method (str | None): Unused; required by Frappe's doc_event signature.

	Raises:
		frappe.DuplicateEntryError: If this is a new Lead and another CRM
			Lead already has the same `mobile_no`.
	"""
	if not doc.is_new() or not doc.mobile_no:
		return

	existing = frappe.db.get_value(
		"CRM Lead", {"mobile_no": doc.mobile_no}, ["name", "lead_name", "mobile_no", "status"], as_dict=True
	)
	if existing:
		frappe.throw(
			DUPLICATE_LEAD_MESSAGE.format(
				name=existing.name,
				lead_name=existing.lead_name or "",
				mobile_no=existing.mobile_no or "",
				status=existing.status or "",
			),
			frappe.DuplicateEntryError,
		)
