# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import hmac
import re

import frappe
from frappe import _

from core_customizations.core_customizations.phone_normalise import is_indian_mobile, normalise
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

BLOCKED_CONTACT_DOCTYPE = "Blocked Contact"

REASON_BLOCKED_LIST = "BLOCKED_LIST"
REASON_FOREIGN_NUMBER = "FOREIGN_NUMBER"

# @businessRule [BR-CRM-002] Every doctype whose own record the voice agent
# can read or write that carries a caller's phone number directly - extend
# this to cover a new one instead of hardcoding another check. `FCRM Note`
# is deliberately not here: it has no phone field of its own (see
# `_get_phone_for_gate`'s special case for it).
CALLER_GATE_PHONE_FIELDS = {
	"CRM Lead": "mobile_no",
	"Contact": "mobile_no",
	"Customer": "mobile_no",
	"CRM Deal": "mobile_no",
	"Quotation": "contact_mobile",
}

# A number's digits, in any of the spellings the blocked-contacts sheet and
# callers use (+91, 91, 0-prefixed, bare 10-digit), still contain a real
# Indian mobile's 10 digits at the end once every non-digit character
# (spaces, dashes, +) is stripped.
_DIGITS_ONLY = re.compile(r"\D")


def get_automation_user():
	"""
	Business Purpose: [BR-CRM-002] The ERPNext user the Sarvam voice agent
	(and any of its tools - direct REST calls to zap.sravie.in, or the
	zap-crm MCP connector) authenticates as for every call, blocked or
	not - read from `Sarvam Voice Agent Settings.caller_gate_automation_user`
	rather than hardcoded, so it can be changed (or caller-gate enforcement
	disabled entirely, by leaving it blank) without a code change.

	Every caller-gate check is scoped to whichever user this returns - a
	staff member signed in as themselves is never affected, whatever is
	configured here.

	Returns:
		str | None: The configured user's id, or None if unset (caller-gate
		enforcement is then a no-op for every doctype hook).
	"""
	return frappe.db.get_single_value(SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user")


def last_10_digits(raw):
	"""
	Business Purpose: [BR-CRM-002] Normalises any spelling of a number
	(+919840456658, 919840456658, 09840456658, 9840456658, or any of those
	with spaces/dashes) to the same last-10-digit string, so the blocked
	list only ever has to store and compare one form.

	Args:
		raw (str | None): A phone number in any format.

	Returns:
		str | None: The last 10 digits, or None if there are fewer than 10
		digits (blank, too short, or not a phone number at all).
	"""
	if not raw:
		return None
	digits = _DIGITS_ONLY.sub("", str(raw))
	if len(digits) < 10:
		return None
	return digits[-10:]


def is_blocked_number(mobile_no):
	"""
	Business Purpose: [BR-CRM-002] Checks a number against the
	`Blocked Contact` list - the single source of truth that replaces
	the Blocked Contacts Google Sheet.

	Args:
		mobile_no (str | None): A phone number in any format.

	Returns:
		bool: True if an *enabled* `Blocked Contact` row matches its last 10
		digits.
	"""
	last10 = last_10_digits(mobile_no)
	if not last10:
		return False
	return bool(frappe.db.exists(BLOCKED_CONTACT_DOCTYPE, {"mobile_no": last10, "enabled": 1}))


def is_foreign_number(mobile_no):
	"""
	Business Purpose: [BR-CRM-002] A non-blank number is "foreign" if it
	does not normalise to an Indian `+91` mobile - reusing
	`phone_normalise.normalise`/`is_indian_mobile` so this agrees with
	every other place in the app that already decides what counts as an
	Indian mobile (e.g. [BR-CRM-001]'s duplicate-lead guard).

	Args:
		mobile_no (str | None): A phone number in any format.

	Returns:
		bool: False for a blank number (never "foreign" - see `evaluate`),
		True for anything non-blank that isn't an Indian +91 mobile.
	"""
	if not mobile_no:
		return False
	return not is_indian_mobile(normalise(mobile_no))


def evaluate(phone):
	"""
	Business Purpose: [BR-CRM-002] The single decision `check()` and the
	doctype guard both defer to, so a caller is judged the same way whether
	the question comes from Sarvam's on-start webhook or from a CRM Lead
	being saved.

	Args:
		phone (str | None): A phone number in any format. Blank/missing is
		allowed - the agent is expected to ask the caller for their number
		in that case, not treat silence as a reason to refuse.

	Returns:
		dict: {allowed, reason, message} - reason is one of
		REASON_BLOCKED_LIST / REASON_FOREIGN_NUMBER / None.
	"""
	phone = (phone or "").strip()
	if not phone:
		return {"allowed": True, "reason": None, "message": ""}

	if is_blocked_number(phone):
		return {
			"allowed": False,
			"reason": REASON_BLOCKED_LIST,
			"message": "This caller is on the blocked list.",
		}

	if is_foreign_number(phone):
		return {
			"allowed": False,
			"reason": REASON_FOREIGN_NUMBER,
			"message": "This is not an Indian number.",
		}

	return {"allowed": True, "reason": None, "message": ""}


WEBHOOK_KEY_PARAM = "key"
WEBHOOK_KEY_HEADER = "X-Webhook-Key"


def _supplied_webhook_key(key=None):
	"""
	The shared secret a caller sent, from the first place it appears:

	1. the `key` argument - a form field, or a field of a JSON body;
	2. the URL query string (`?key=`) - which Frappe drops from the method's
	   arguments when the body is JSON (`frappe.app.make_form_dict` then
	   builds them from the JSON alone), so it is read off the request here;
	3. the `X-Webhook-Key` request header.
	"""
	if key:
		return str(key)
	request = getattr(frappe.local, "request", None)
	if request is None:
		return None
	return request.args.get(WEBHOOK_KEY_PARAM) or request.headers.get(WEBHOOK_KEY_HEADER) or None


def _check_webhook_key(key=None):
	"""
	Authenticates a Sarvam call against Sarvam Voice Agent Settings'
	`webhook_secret`, wherever the caller put the key (see
	`_supplied_webhook_key`). Compared in constant time. A missing or empty
	key, or no secret configured, is always refused.

	Raises:
		frappe.PermissionError: "Unauthorized request".
	"""
	supplied = _supplied_webhook_key(key)
	webhook_secret = frappe.get_cached_doc(SARVAM_SETTINGS_DOCTYPE).get_password(
		"webhook_secret", raise_exception=False
	)
	if not supplied or not webhook_secret or not hmac.compare_digest(supplied.encode(), webhook_secret.encode()):
		frappe.throw(_("Unauthorized request"), exc=frappe.PermissionError)


def without_webhook_key(payload=None, headers=None):
	"""
	Copies of a request payload / its headers with the shared secret removed,
	for anything that gets logged (Integration Request): the `key` field a
	form-encoded or JSON body may carry, and the `X-Webhook-Key` header.

	Returns:
		tuple: (payload dict | original non-dict value, headers dict | None).
	"""
	if isinstance(payload, dict):
		payload = {k: v for k, v in payload.items() if k != WEBHOOK_KEY_PARAM}
	if headers is not None:
		headers = {k: v for k, v in dict(headers).items() if k.lower() != WEBHOOK_KEY_HEADER.lower()}
	return payload, headers


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def check(phone: str | None = None, key: str | None = None):
	"""
	Business Purpose: [BR-CRM-002] The server-side caller gate Sarvam's
	on-start webhook (or any other call-start hook) calls instead of the
	Blocked Contacts Google Sheet's Apps Script, so "is this caller
	allowed" is decided once, on the server, the same way the doctype
	guard below decides it for every CRM write.

	Authenticated the same way as `sarvam_telephony.handle_outbound_webhook`/
	`handle_inbound_webhook` - the `key` query param matched against
	Sarvam Voice Agent Settings' `webhook_secret` - so the existing secret
	can be reused and the Apps Script retired without provisioning
	anything new.

	Args:
		phone (str | None): The caller's number, in any format. Blank is
			allowed (the agent should ask the caller for their number).
		key (str | None): Must match `Sarvam Voice Agent Settings.webhook_secret`.

	Returns:
		dict: {allowed, reason, message} - see `evaluate`.

	Raises:
		frappe.PermissionError: If `key` doesn't match.
	"""
	_check_webhook_key(key)
	return evaluate(phone)


@frappe.whitelist()
def lookup_by_phone(phone: str | None = None):
	"""
	Business Purpose: [BR-CRM-002] Lets the configured caller-gate
	automation user resolve a CRM Lead/Contact by phone number regardless
	of crm's own org-hierarchy ownership restriction
	(`crm.permissions.org_hierarchy`), which otherwise limits a plain
	`Sales User` - what this integration account actually is - to Leads it
	owns or is assigned to via ToDo, not every Lead in the system. Without
	this, the voice agent could never find an existing caller's Lead
	unless it happened to be owned by (or assigned to) the automation
	account itself.

	The permission bypass is scoped to the Lead lookup only, and only for
	the configured automation user - for any other caller this is an
	ordinary, permission-respecting lookup (no bypass), so it never
	broadens anyone else's access; a staff Sales User calling this still
	only sees Leads org-hierarchy already lets them see. Contact has no
	such ownership restriction to bypass, so its lookup always goes
	through normal permissions, which already applies [BR-CRM-002]'s own
	`permission_query_conditions_contact`.

	Bypassing permissions for the Lead lookup also bypasses caller_gate's
	own `permission_query_conditions_crm_lead` hook - `ignore_permissions`
	skips every permission-query-condition, including ours - so this
	function re-asserts that exact check manually before querying,
	instead of relying on the hook, to keep [BR-CRM-002] closed on this
	path.

	Args:
		phone (str | None): The caller's number, in any format. Blank
			returns both as None without querying.

	Returns:
		dict: {"lead": {...} | None, "contact": {...} | None,
		"customer": {...} | None}. "lead" is {name, lead_name, mobile_no,
		status, organization}; "contact" is {name, full_name, mobile_no};
		"customer", resolved by `_resolve_customer`, is {name,
		customer_name, customer_group, default_price_list}.

	Raises:
		frappe.ValidationError: If called by the configured automation
			user for a blocked or foreign number - the fixed
			`CALLER_BLOCKED: ...` token, same as `guard_caller_gate`.
	"""
	if not (phone or "").strip():
		return {"lead": None, "contact": None, "customer": None}

	is_automation_user = frappe.session.user == get_automation_user()
	if is_automation_user:
		result = evaluate(phone)
		if not result["allowed"]:
			frappe.throw(
				f"CALLER_BLOCKED: reason={result['reason']}; mobile_no={phone}",
				frappe.ValidationError,
			)

	# [BR-CRM-002] Matches whichever spelling the record's own mobile_no
	# happens to be stored in (+91..., bare 91..., or bare 10-digit) -
	# older records predate the before_validate normalisation hook and are
	# never rewritten by it retroactively, so an exact match on only the
	# fully-normalised spelling silently misses them. Same three spellings
	# Sarvam's own lookup_caller_lead/lookup_caller_contact tools already
	# match against.
	normalised = normalise(phone) or phone
	spellings = [normalised, normalised[-12:], normalised[-10:]]

	leads = frappe.get_list(
		"CRM Lead",
		filters={"mobile_no": ("in", spellings)},
		fields=["name", "lead_name", "mobile_no", "status", "organization"],
		limit=1,
		ignore_permissions=is_automation_user,
	)
	contacts = frappe.get_list(
		"Contact",
		filters={"mobile_no": ("in", spellings)},
		fields=["name", "full_name", "mobile_no"],
		limit=1,
	)

	lead = leads[0] if leads else None
	contact = contacts[0] if contacts else None

	return {
		"lead": lead,
		"contact": contact,
		"customer": _resolve_customer(lead, contact),
	}


def _resolve_customer(lead, contact):
	"""
	Business Purpose: [BR-CRM-002] Replicates, in one call, the two ways
	Sarvam's own on-start tools resolve a caller's Customer today -
	`lookup_caller_contact`'s join from the Contact to its Customer via the
	`Dynamic Link` child table, and `lookup_contact_customer`'s fallback of
	matching the Lead's `organization` against an enabled Customer's exact
	`customer_name` (`lookup_lead_organization` reads the field that feeds
	this). A real caller can resolve through only one of the two: a Lead's
	free-text `organization` need not exactly match any Customer's name
	even when the same caller already has a Contact properly linked to one
	via `Dynamic Link` (and vice versa, a caller with no Contact yet but an
	organization that happens to match an existing Customer).

	When both resolve, the organization match wins - the same precedence
	Sarvam's own tools have today purely from their execution order
	(`lookup_caller_contact` first, `lookup_contact_customer` last, both
	writing the same `crm_customer_id` variable), now made explicit here
	instead of being an accident of two tools' relative ordering.

	Args:
		lead (dict | None): As returned by the CRM Lead query above, must
			include "organization".
		contact (dict | None): As returned by the Contact query above,
			must include "name".

	Returns:
		dict | None: {name, customer_name, customer_group,
		default_price_list}, or None if neither path resolves a Customer.
	"""
	customer_fields = ["name", "customer_name", "customer_group", "default_price_list"]
	customer = None

	if contact:
		link_name = frappe.db.get_value(
			"Dynamic Link",
			{"parenttype": "Contact", "parent": contact["name"], "link_doctype": "Customer"},
			"link_name",
		)
		if link_name:
			customer = frappe.db.get_value("Customer", link_name, customer_fields, as_dict=True)

	if lead and lead.get("organization"):
		matched = frappe.get_list(
			"Customer",
			filters={"customer_name": lead["organization"], "disabled": 0},
			fields=customer_fields,
			limit=1,
		)
		if matched:
			customer = matched[0]

	return customer


def _get_phone_for_gate(doc):
	"""
	Business Purpose: [BR-CRM-002] Resolves the phone number to judge a
	write by. Every doctype in `CALLER_GATE_PHONE_FIELDS` carries its own
	caller number directly; `FCRM Note` does not, so a Note is judged by
	whatever record it is attached to (its `reference_doctype`/
	`reference_docname`) - the same Lead/Contact/Deal/Customer the note is
	about, not the Note itself.

	Args:
		doc (Document): The document being saved.

	Returns:
		str | None: A phone number in whatever format it is stored, or
		None if there is nothing to judge (e.g. a Note on a doctype this
		gate does not cover).
	"""
	if doc.doctype == "FCRM Note":
		reference_doctype = doc.get("reference_doctype")
		reference_name = doc.get("reference_docname")
		field = CALLER_GATE_PHONE_FIELDS.get(reference_doctype)
		if not field or not reference_name:
			return None
		return frappe.db.get_value(reference_doctype, reference_name, field)

	field = CALLER_GATE_PHONE_FIELDS.get(doc.doctype)
	return doc.get(field) if field else None


def guard_caller_gate(doc, method=None):
	"""
	Business Purpose: [BR-CRM-002] Refuses to let the Sarvam automation
	user create or edit a CRM record for a blocked or foreign caller, on
	the server - so this holds regardless of what the agent's prompt does
	or doesn't check first. Scoped to `get_automation_user()`: a staff
	member saving the same record as themselves is never affected.

	Runs on `validate`, so it fires on every save (insert and update), not
	just creation - the same reasoning [BR-CRM-001]'s duplicate-lead guard
	uses for running after normalisation rather than on `before_insert`.

	Set `doc.flags.ignore_caller_gate` to bypass (e.g. a data import run by
	Administrator never needs this - that path is already excluded by the
	automation-user scoping, but the flag exists for the rare case a
	script needs to act as that user without the gate, the same bypass
	convention `contact_lead_link.py` uses for its own loopback flag).

	Args:
		doc (Document): The document being saved.
		method (str | None): Unused; required by Frappe's doc_event signature.

	Raises:
		frappe.ValidationError: If the session user is the configured
			automation user and the resolved phone number is blocked or
			foreign. The message is the fixed `CALLER_BLOCKED: ...` token
			the agent's prompt parses - never translated or reworded.
	"""
	automation_user = get_automation_user()
	if not automation_user or doc.flags.get("ignore_caller_gate") or frappe.session.user != automation_user:
		return

	phone = _get_phone_for_gate(doc)
	if not phone:
		return

	result = evaluate(phone)
	if not result["allowed"]:
		frappe.throw(
			f"CALLER_BLOCKED: reason={result['reason']}; mobile_no={phone}",
			frappe.ValidationError,
		)


def _permission_query_condition(doctype, mobile_field, user=None):
	"""
	Business Purpose: [BR-CRM-002] The SQL half of the same rule
	`guard_caller_gate` enforces on writes - a list/search query made as
	the configured automation user must not even return a row whose
	number is blocked or foreign, not just be refused when it tries to
	act on one.

	Written as a raw WHERE-fragment (the `permission_query_conditions`
	hook contract) rather than calling `evaluate()` per row, since that
	hook has no per-row Python callback - only a string spliced into the
	query. `regexp_replace`/`regexp` need MariaDB 10.0.5+ (standard on any
	current Frappe install). No user input reaches this string - `user`
	is only ever compared, never interpolated - so there is nothing here
	for a caller to inject.

	Args:
		doctype (str): The doctype this condition is being built for -
			must match a key in `CALLER_GATE_PHONE_FIELDS`.
		mobile_field (str): That doctype's own phone fieldname.
		user (str | None): Defaults to `frappe.session.user`.

	Returns:
		str: A SQL boolean expression, or "" (no restriction) when
		caller-gate enforcement is unconfigured, or the querying user
		isn't the configured automation user.
	"""
	automation_user = get_automation_user()
	if not automation_user or (user or frappe.session.user) != automation_user:
		return ""

	digits = f"regexp_replace(`tab{doctype}`.`{mobile_field}`, '[^0-9]', '')"
	return f"""(
		ifnull(`tab{doctype}`.`{mobile_field}`, '') = ''
		or (
			{digits} regexp '^(0091|91|0)?[6-9][0-9]{{9}}$'
			and right({digits}, 10) not in (
				select `mobile_no` from `tab{BLOCKED_CONTACT_DOCTYPE}` where `enabled` = 1
			)
		)
	)"""


def get_permission_query_conditions_crm_lead(user=None):
	return _permission_query_condition("CRM Lead", "mobile_no", user)


def get_permission_query_conditions_contact(user=None):
	return _permission_query_condition("Contact", "mobile_no", user)


def get_permission_query_conditions_customer(user=None):
	return _permission_query_condition("Customer", "mobile_no", user)


def get_permission_query_conditions_crm_deal(user=None):
	return _permission_query_condition("CRM Deal", "mobile_no", user)


def get_permission_query_conditions_quotation(user=None):
	return _permission_query_condition("Quotation", "contact_mobile", user)


def has_permission(doc, user=None, permission_type=None):
	"""
	Business Purpose: [BR-CRM-002] Backstops `get_permission_query_conditions_*`
	for a single-document fetch (`frappe.client.get`, `GET
	/api/resource/<DocType>/<name>`) - that path resolves the document
	first and checks `has_permission` on it, rather than running a
	filtered list query, so the SQL condition alone would never see it.

	Args:
		doc (Document): The document being accessed.
		user (str | None): Defaults to `frappe.session.user`.
		permission_type (str | None): Unused - a blocked/foreign caller's
			record is off-limits to the configured automation user for
			read, write and delete alike, not just one of them.

	Returns:
		bool: False to deny, True to defer to Frappe's normal permission
		checks (this hook only ever narrows access, never grants it).
	"""
	automation_user = get_automation_user()
	if not automation_user or (user or frappe.session.user) != automation_user:
		return True

	phone = _get_phone_for_gate(doc)
	if not phone:
		return True

	return evaluate(phone)["allowed"]


BLOCKED_CONTACT_REQUEST_DOCTYPE = "Blocked Contact Request"


@frappe.whitelist()
def escalate_lead_for_blocking(lead: str, reason: str):
	"""
	Business Purpose: [BR-CRM-003] The one-click entry point the "Escalate
	for Blocking" button on the CRM Lead form calls - raises a `Blocked
	Contact Request` for the Lead's own number and immediately submits it
	(the Draft -> Pending workflow transition), landing it in front of
	whoever has the System Manager role to approve or reject. Creation and
	submission are both gated by `Blocked Contact Request`'s own doctype
	permissions (`create`/`submit`, restricted to the `Sales User` and
	`System Manager` roles) - this function does not re-implement that
	check, only the business-specific ones (the Lead must be readable and
	have a number to escalate).

	Args:
		lead (str): Name of the CRM Lead being escalated.
		reason (str): Why this number should be blocked - becomes the new
			request's `reason` field.

	Returns:
		str: Name of the created (and submitted) `Blocked Contact Request`.

	Raises:
		frappe.PermissionError: If the user cannot read the Lead, or lacks
			`create`/`submit` permission on `Blocked Contact Request`.
		frappe.ValidationError: If the Lead has no mobile number, no reason
			was given, or it already has an open escalation.
	"""
	if not frappe.has_permission("CRM Lead", "read", lead):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required to escalate a number for blocking."))

	request = frappe.get_doc({"doctype": BLOCKED_CONTACT_REQUEST_DOCTYPE, "lead": lead, "reason": reason}).insert()
	request.submit()
	return request.name


def _get_or_create_blocked_contact(mobile_no, reason, added_by):
	"""
	Business Purpose: [BR-CRM-003] The side effect of a `Blocked Contact
	Request` being Approved. Reuses an existing `Blocked Contact` row for
	the same number (re-enabling it if it had been disabled) rather than
	risking a second row for the same last-10-digits - `mobile_no` is
	`unique` on that doctype, so inserting a genuine duplicate would fail
	anyway, but reusing is the more useful behaviour than erroring.

	Args:
		mobile_no (str): The escalated number, in whatever format the
			Lead had it in - normalised the same way every other
			`Blocked Contact` row is.
		reason (str): Copied from the request onto a newly created row;
			left alone on a reused row (not overwritten with a second
			escalation's reason).
		added_by (str): The user credited with adding a newly created row.

	Returns:
		Document: The (possibly newly created) `Blocked Contact`.
	"""
	last10 = last_10_digits(mobile_no)
	existing_name = frappe.db.exists(BLOCKED_CONTACT_DOCTYPE, {"mobile_no": last10})
	if existing_name:
		blocked = frappe.get_doc(BLOCKED_CONTACT_DOCTYPE, existing_name)
		if not blocked.enabled:
			blocked.enabled = 1
			blocked.save(ignore_permissions=True)
		return blocked

	return frappe.get_doc(
		{
			"doctype": BLOCKED_CONTACT_DOCTYPE,
			"mobile_no": mobile_no,
			"reason": reason,
			"added_by": added_by,
			"enabled": 1,
		}
	).insert(ignore_permissions=True)


def handle_blocked_contact_request_update(doc, method=None):
	"""
	Business Purpose: [BR-CRM-003] Creates (or reuses) the `Blocked
	Contact` the moment a request's workflow reaches "Approved" - the
	actual enforcement in [BR-CRM-002] only ever looks at `Blocked
	Contact`, so this is what makes an approval actually take effect
	rather than just recording a decision.

	Registered on `on_update`, which fires on every save of this
	doctype (including the Draft -> Pending submit) - the `workflow_state`
	check means only the Approve transition (Pending -> Approved, a plain
	save at docstatus 1) actually does anything; `blocked_contact` already
	being set guards against doing it twice (e.g. a redundant save while
	already Approved).

	Args:
		doc (Document): The `Blocked Contact Request` being saved.
		method (str | None): Unused; required by Frappe's doc_event signature.
	"""
	if doc.workflow_state != "Approved" or doc.blocked_contact:
		return

	blocked = _get_or_create_blocked_contact(doc.mobile_no, doc.reason, doc.requested_by)
	doc.db_set("blocked_contact", blocked.name, update_modified=False)


def handle_blocked_contact_request_cancel(doc, method=None):
	"""
	Business Purpose: [BR-CRM-003] Reverses an approval. The workflow lets
	System Manager Reject either directly from Pending or from Approved
	(cancelling the request either way, since Rejected is a `doc_status
	"2"` state) - only the latter case has a `Blocked Contact` to undo.
	Disables rather than deletes it: the number stays visible in the
	`Blocked Contact` list with its history, just no longer enforced.

	Registered on `on_cancel` (not `on_update` - Frappe's cancel flow does
	not fire `on_update`).

	Args:
		doc (Document): The `Blocked Contact Request` being cancelled
			(i.e. moved to the Rejected state).
		method (str | None): Unused; required by Frappe's doc_event signature.
	"""
	if doc.blocked_contact:
		frappe.db.set_value(BLOCKED_CONTACT_DOCTYPE, doc.blocked_contact, "enabled", 0)
