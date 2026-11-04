# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Server-side jobs for the Sarvam "Sravi Enterprises Customer Care" voice agent.

Each whitelisted method here replaces a chain of generic ERPNext tool calls the
agent's model used to orchestrate itself (repeated lookups, arithmetic it got
wrong, multi-step saves that failed half-way) with one call per job:

- call_started / caller_context  [BR-TEL-007]  who is calling, before the agent speaks
- get/set_caller_preferences     [BR-CRM-007]  per-caller JSON preferences
- upsert_quote                   [BR-CRM-006]  a real draft Quotation; the agent reads its totals
- save_request                   [BR-CRM-004]  CRM Lead / Deal / Quotation / callback Task, one transaction
- transfer_target                [BR-TEL-006]  who to transfer a live call to, if anyone (named, sticky, round robin, busy)
- orderable_items                [BR-CRM-006]  the items a retailer / wholesale / distributor may order

The call-ended half of [BR-TEL-007] is `apply_call_outcome`, called from
`sarvam_telephony.handle_inbound_webhook`.

Conventions shared with `caller_gate.check`:
- Webhook-style: `allow_guest=True`, authenticated by `_check_webhook_key(key)`.
- `caller_gate.evaluate(phone)` runs first; a blocked/foreign caller gets
  {allowed: false, reason, message} and nothing is read or written.
- Every read and write runs as the configured Caller Gate Automation User, so
  [BR-CRM-002]'s doctype guards (CALLER_BLOCKED) and [BR-CRM-001]'s
  (DUPLICATE_LEAD) still fire on every write this module makes.
- A caller's number is matched on its last 10 digits, ignoring spaces, dashes
  and +91/91/0 prefixes, so legacy rows like "98411 02004" still match.
- Business values (executives, hours, categories, pack items) live in
  Sarvam Voice Agent Settings, never in this file.
"""

import json
import re
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.integrations.utils import create_request_log
from frappe.utils import add_to_date, cint, flt, get_system_timezone, get_time, now_datetime, nowdate

from core_customizations.core_customizations import quotation_gst
from core_customizations.core_customizations.caller_gate import (
	_PHONE_HASH,
	_check_webhook_key,
	_indian_mobile,
	_resolve_customer,
	is_blocked_number,
	number_for_hash,
	without_webhook_key,
	evaluate,
	get_automation_user,
	last_10_digits,
)
from core_customizations.core_customizations.lead_duplicate_guard import DUPLICATE_LEAD_MESSAGE
from core_customizations.core_customizations.phone_normalise import MOBILE, normalise
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

CLOSED_DEAL_STATUSES = ("Won", "Lost")
OPEN_TASK_STATUSES = ("Backlog", "Todo", "In Progress")
# [BR-CRM-004] First words of a callback Task saved from a number the caller
# spoke (save_request's `callback_number`), not the number Sarvam saw.
CALLBACK_NUMBER_NOTE = "Callback request (number given by the caller, not the line):"
# [BR-CRM-004] Every voice-agent callback Task's title starts with this - the
# Callbacks workspace (callbacks_dashboard) counts Tasks by it.
CALLBACK_TASK_TITLE_PREFIX = "Callback:"

# Keys read from the call-ended webhook's `output_agent_variables`. Sarvam's
# inbound payload shape is not yet confirmed against a real delivery (see
# `handle_inbound_webhook`) - the whole dict is always stored on the Call Log
# as well, so a renamed key is visible and nothing is lost.
SUMMARY_KEYS = ("summary", "call_summary")
CONVERSATION_REF_KEYS = ("conversation_ref", "conversation_id")
PREFERENCES_KEY = "preferences"

# Keys a call-started webhook may carry the caller's number / call id under.
CALLER_PHONE_KEYS = ("user_phone_number", "phone", "caller_number", "from")
CALL_ID_KEYS = ("interaction_id", "call_id")


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _settings():
	return frappe.get_cached_doc(SARVAM_SETTINGS_DOCTYPE)


@contextmanager
def _as_automation_user():
	"""
	[BR-CRM-002] Every read/write here runs as the configured automation user
	- the guest webhook session has no rights of its own, and running as that
	user is what keeps caller_gate's own doctype guards in force.
	"""
	user = get_automation_user()
	if not user:
		frappe.throw(_("Caller Gate Automation User is not set in Sarvam Voice Agent Settings."))
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		yield user
	finally:
		frappe.set_user(previous)


def _blocked(gate, **extra):
	return {**gate, **extra}


def _error(code, message, **extra):
	return {"allowed": True, "status": "error", "error": code, "message": message, **extra}


def _canonical(phone):
	"""+91XXXXXXXXXX for anything normalise() recognises, else the input stripped."""
	phone = (phone or "").strip()
	return normalise(phone) or phone


def _match_sql(column):
	return f"right(regexp_replace(ifnull({column}, ''), '[^0-9]', ''), 10) = %(last10)s"


def _find_lead(last10):
	rows = frappe.db.sql(
		f"""select name, lead_name, mobile_no, status, organization, lead_owner,
		           custom_caller_category as caller_category, custom_store_type as store_type
		    from `tabCRM Lead`
		    where {_match_sql('mobile_no')} or {_match_sql('phone')}
		    order by creation asc limit 1""",
		{"last10": last10},
		as_dict=True,
	)
	return rows[0] if rows else None


def _find_contact(last10):
	rows = frappe.db.sql(
		f"""select c.name, c.full_name, c.mobile_no from `tabContact` c
		    where {_match_sql('c.mobile_no')}
		       or exists (select 1 from `tabContact Phone` cp
		                  where cp.parenttype = 'Contact' and cp.parent = c.name and {_match_sql('cp.phone')})
		    order by c.creation asc limit 1""",
		{"last10": last10},
		as_dict=True,
	)
	return rows[0] if rows else None


def _find_customer_by_mobile(last10):
	rows = frappe.db.sql(
		f"""select name from `tabCustomer` where disabled = 0 and {_match_sql('mobile_no')}
		    order by creation asc limit 1""",
		{"last10": last10},
		pluck=True,
	)
	if not rows:
		return None
	return frappe.db.get_value(
		"Customer", rows[0], ["name", "customer_name", "customer_group", "default_price_list"], as_dict=True
	)


def _resolve(phone):
	"""
	[BR-CRM-002] The caller's CRM Lead, Contact and Customer, matched on the
	last 10 digits of any stored spelling. Customer resolution is
	`caller_gate._resolve_customer` - the same order `lookup_by_phone` uses -
	with one fallback only when neither of its paths finds anything: a
	Customer whose own `mobile_no` matches.
	"""
	last10 = last_10_digits(phone)
	if not last10:
		return frappe._dict(lead=None, contact=None, customer=None, phone=_canonical(phone))

	lead = _find_lead(last10)
	contact = _find_contact(last10)
	customer = _resolve_customer(lead, contact) or _find_customer_by_mobile(last10)
	if customer:
		customer = frappe._dict(customer)
		customer.category = _category_for_group(customer.customer_group)
		customer.group_supported = customer.category is not None
	return frappe._dict(lead=lead, contact=contact, customer=customer, phone=_canonical(phone))


def _public_lead(lead):
	if not lead:
		return None
	return {k: lead.get(k) for k in ("name", "lead_name", "mobile_no", "status", "organization", "caller_category", "store_type")}


def _public_customer(customer):
	if not customer:
		return None
	return {
		k: customer.get(k)
		for k in ("name", "customer_name", "customer_group", "default_price_list", "category", "group_supported")
	}


def _category_rows(category):
	category = (category or "").strip().lower()
	return [r for r in _settings().caller_categories if (r.category or "").strip().lower() == category]


def _category_default(category):
	rows = _category_rows(category)
	return next((r for r in rows if r.is_default), None)


def _category_for_group(customer_group):
	row = next((r for r in _settings().caller_categories if r.customer_group == customer_group), None)
	return row.category if row else None


def _parse_json_arg(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, str):
		try:
			return json.loads(value)
		except ValueError:
			frappe.throw(_("Expected JSON, got: {0}").format(value[:200]))
	return value


def _parse_items(items):
	"""[{item_code, qty}] - returns (items, error_message)."""
	items = _parse_json_arg(items, [])
	if isinstance(items, dict):
		items = [items]
	if not isinstance(items, list):
		return None, "items must be a list of {item_code, qty}"
	parsed = []
	for row in items:
		if not isinstance(row, dict) or not row.get("item_code"):
			return None, "every item needs an item_code"
		qty = flt(row.get("qty") or 0)
		if qty <= 0:
			return None, f"qty for {row.get('item_code')} must be more than 0"
		parsed.append({"item_code": row["item_code"], "qty": qty})
	return parsed, None


# --------------------------------------------------------------------------
# Saved addresses  [BR-CRM-008]
# --------------------------------------------------------------------------

ADDRESS_FIELDS = (
	"name",
	"address_title",
	"address_type",
	"address_line1",
	"address_line2",
	"city",
	"state",
	"pincode",
	"is_primary_address",
	"is_shipping_address",
)


def _address_owner(ctx):
	"""
	[BR-CRM-008] Whose Addresses a caller has: their Customer's if they have
	one, otherwise their CRM Lead's (linked by save_request). Never guessed
	from the Lead's free-text company_description.
	"""
	if ctx.customer:
		return "Customer", ctx.customer.name
	if ctx.lead:
		return "CRM Lead", ctx.lead["name"]
	return None


def _linked_addresses(owner, limit=None):
	"""Enabled Addresses linked to `owner` - shipping first, then primary, then newest edit."""
	if not owner:
		return []
	columns = ", ".join(f"a.`{f}`" for f in ADDRESS_FIELDS)
	return frappe.db.sql(
		f"""select distinct {columns}, a.modified from `tabAddress` a
		    join `tabDynamic Link` dl on dl.parenttype = 'Address' and dl.parent = a.name
		    where dl.link_doctype = %(doctype)s and dl.link_name = %(name)s and ifnull(a.disabled, 0) = 0
		    order by a.is_shipping_address desc, a.is_primary_address desc, a.modified desc
		    {'limit %(limit)s' if limit else ''}""",
		{"doctype": owner[0], "name": owner[1], "limit": cint(limit)},
		as_dict=True,
	)


def _caller_addresses(ctx):
	rows = _linked_addresses(_address_owner(ctx), cint(_settings().address_list_limit) or None)
	return [{f: row.get(f) for f in ADDRESS_FIELDS} for row in rows]


def _owned_address(ctx, address_name):
	"""
	The caller's own enabled Address named `address_name`, or an
	ADDRESS_NOT_ON_RECORD error - nothing from an Address the caller does not
	own is ever used.
	"""
	owner = _address_owner(ctx)
	match = next((a for a in _linked_addresses(owner) if a.name == address_name), None) if owner else None
	if not match:
		return None, _error(
			"ADDRESS_NOT_ON_RECORD",
			"That saved address isn't on this caller's record - ask for the delivery address again.",
			address_name=address_name,
		)
	return match, None


def _address_text(address):
	parts = [address.get("address_line1"), address.get("address_line2"), address.get("city"), address.get("state")]
	text = ", ".join(p.strip() for p in parts if p and p.strip())
	return f"{text} {address.get('pincode') or ''}".strip()


# --------------------------------------------------------------------------
# 1. Call started / caller context  [BR-TEL-007]
# --------------------------------------------------------------------------


def _preferences(ctx):
	for doctype, record in (("CRM Lead", ctx.lead), ("Contact", ctx.contact)):
		if record:
			raw = frappe.db.get_value(doctype, record["name"], "custom_caller_preferences")
			if raw:
				prefs = _parse_json_arg(raw, {})
				return prefs if isinstance(prefs, dict) else {}, f"{doctype}:{record['name']}"
	source = (
		f"CRM Lead:{ctx.lead['name']}" if ctx.lead else (f"Contact:{ctx.contact['name']}" if ctx.contact else None)
	)
	return {}, source


def _ensure_call_log(call_id, ctx, to_number=None):
	"""
	[BR-TEL-007] One CRM Call Log per Sarvam interaction. `CRM Call Log` is
	autonamed `field:id`, so keying it by Sarvam's interaction_id makes the
	call-started webhook, any repeat of it, and the call-ended webhook
	(`handle_inbound_webhook`) all land on the same record.
	"""
	if frappe.db.exists("CRM Call Log", call_id):
		return {"id": call_id, "created": False}

	log = frappe.new_doc("CRM Call Log")
	log.id = call_id
	log.type = "Incoming"
	log.telephony_medium = "Sarvam"
	log.status = "In Progress"
	log.start_time = frappe.utils.now_datetime()
	setattr(log, "from", ctx.phone)
	# `to` is mandatory on CRM Call Log; the call-started payload may not name
	# the number dialled, so fall back to the agent's own configured caller ID.
	log.to = to_number or _settings().support_agent_phone_number
	if not log.to:
		log.flags.ignore_mandatory = True
	if ctx.lead:
		log.reference_doctype, log.reference_docname = "CRM Lead", ctx.lead["name"]
	elif ctx.contact:
		log.reference_doctype, log.reference_docname = "Contact", ctx.contact["name"]
	try:
		log.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		# Two deliveries of the same call-started webhook racing each other.
		return {"id": call_id, "created": False}
	return {"id": log.name, "created": True}


def _caller_context(phone, call_id=None, to_number=None):
	gate = evaluate(phone)
	if not gate["allowed"]:
		return gate

	with _as_automation_user():
		ctx = _resolve(phone)
		preferences, source = _preferences(ctx)
		call_log = _ensure_call_log(call_id, ctx, to_number) if call_id else None
		addresses = _caller_addresses(ctx)

	return {
		**gate,
		"lead": _public_lead(ctx.lead),
		"contact": ctx.contact,
		"customer": _public_customer(ctx.customer),
		"preferences": preferences,
		"preferences_source": source,
		"call_log": call_log,
		"addresses": addresses,
	}


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def caller_context(phone: str | None = None, key: str | None = None, call_id: str | None = None):
	"""
	Business Purpose: [BR-TEL-007] Everything the agent needs about a caller
	before it speaks, in one call - replaces check_blocked,
	lookup_caller_lead, lookup_caller_contact, lookup_lead_organization,
	lookup_contact_customer, fetch_caller_preferences, fetch_user_metadata
	and create_call_log.

	Args:
		phone (str | None): The caller's number, any spelling.
		key (str | None): Must match Sarvam Voice Agent Settings.webhook_secret.
		call_id (str | None): Sarvam's interaction_id. When given, the CRM
			Call Log for it is created (once - a repeat returns the same one).

	Returns:
		dict: {allowed, reason, message, lead, contact, customer, preferences,
		preferences_source, call_log}, or just {allowed: false, reason,
		message} for a blocked/foreign caller.
	"""
	_check_webhook_key(key)
	return _caller_context(phone, call_id)


def _request_payload(kwargs):
	request = getattr(frappe, "request", None)
	payload = (request.get_json(silent=True) if request else None) or {}
	return {**{k: v for k, v in kwargs.items() if k != "cmd"}, **payload}


def _first(payload, keys):
	return next((payload.get(k) for k in keys if payload.get(k)), None)


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def call_started(**kwargs):
	"""
	Business Purpose: [BR-TEL-007] Sarvam's call-started webhook. Logs the
	raw payload (as `handle_inbound_webhook` does for call-ended, so any
	drift in Sarvam's payload shape is visible), creates the call's CRM Call
	Log keyed by its interaction_id, and returns the same caller context as
	`caller_context` for the agent to start the conversation with.

	Configure on the Sarvam deployment as:
	`<site>/api/method/core_customizations.core_customizations.voice_agent.call_started?key=<webhook_secret>`
	"""
	_check_webhook_key(kwargs.get("key"))

	payload, _headers = without_webhook_key(_request_payload(kwargs))
	create_request_log(
		payload,
		request_description="Sarvam Call Started",
		service_name="Sarvam",
		is_remote_request=1,
		status="Completed",
	)
	return _caller_context(
		_first(payload, CALLER_PHONE_KEYS),
		_first(payload, CALL_ID_KEYS),
		payload.get("agent_phone_number"),
	)


# --------------------------------------------------------------------------
# 2. Caller preferences  [BR-CRM-007]
# --------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def get_caller_preferences(phone: str | None = None, key: str | None = None):
	"""
	Business Purpose: [BR-CRM-007] The caller's stored preferences - the
	`custom_caller_preferences` JSON on their CRM Lead, else on their Contact.

	Returns:
		dict: {allowed, preferences: {...}, source: "CRM Lead:<name>" |
		"Contact:<name>" | None}.
	"""
	_check_webhook_key(key)
	gate = evaluate(phone)
	if not gate["allowed"]:
		return gate
	with _as_automation_user():
		preferences, source = _preferences(_resolve(phone))
	return {**gate, "preferences": preferences, "source": source}


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def set_caller_preferences(
	phone: str | None = None, key: str | None = None, preferences: str | dict | None = None, merge: int = 1
):
	"""
	Business Purpose: [BR-CRM-007] Saves the caller's preferences on their
	CRM Lead (else their Contact). `merge` (default) keeps keys not mentioned
	this time; `merge=0` replaces the whole object.

	Written with `db.set_value` rather than a full document save: the caller
	gate has already been evaluated above, and a full save of a legacy Lead
	or Contact can fail unrelated validation (e.g. a Lead that predates the
	mandatory `lead_owner`) - a preference write must not depend on that.

	Returns:
		dict: {allowed, saved, preferences, source}, or {..., saved: false,
		error: "NOT_ON_RECORD"} when the caller has no Lead or Contact yet.
	"""
	_check_webhook_key(key)
	gate = evaluate(phone)
	if not gate["allowed"]:
		return gate

	new = _parse_json_arg(preferences, {})
	if not isinstance(new, dict):
		return _error("INVALID_PREFERENCES", "preferences must be a JSON object")

	with _as_automation_user():
		ctx = _resolve(phone)
		target = ("CRM Lead", ctx.lead["name"]) if ctx.lead else (("Contact", ctx.contact["name"]) if ctx.contact else None)
		if not target:
			return {**gate, "saved": False, "error": "NOT_ON_RECORD", "preferences": new, "source": None}
		current = _parse_json_arg(frappe.db.get_value(*target, "custom_caller_preferences"), {}) if cint(merge) else {}
		merged = {**(current if isinstance(current, dict) else {}), **new}
		frappe.db.set_value(*target, "custom_caller_preferences", json.dumps(merged))
	return {**gate, "saved": True, "preferences": merged, "source": f"{target[0]}:{target[1]}"}


# --------------------------------------------------------------------------
# 3. Quote  [BR-CRM-006]
# --------------------------------------------------------------------------


def _quote_company():
	return _settings().quotation_company or frappe.defaults.get_global_default("company")


def _open_deal(ctx):
	"""
	[BR-CRM-004] The caller's newest open CRM Deal: for a caller with a CRM
	Lead, the Deal of that Lead; otherwise a Deal whose number is the
	caller's, or that has the caller's Contact in its Contacts table.

	CRM Deal takes `mobile_no` from its primary Contact on every save (blank
	when it has none), so a Customer's Deal is found through its Contact row
	first - matching on `mobile_no` alone missed every Deal created without a
	Contact, and each later quote or save opened another one.
	"""
	filters = {"status": ("not in", CLOSED_DEAL_STATUSES)}
	if ctx.lead:
		filters["lead"] = ctx.lead["name"]
		return frappe.db.get_value("CRM Deal", filters, "name", order_by="creation desc")
	rows = frappe.db.sql(
		f"""select d.name from `tabCRM Deal` d
		    where d.status not in %(closed)s
		      and ({_match_sql('d.mobile_no')}
		           or exists (select 1 from `tabCRM Contacts` cc
		                      where cc.parenttype = 'CRM Deal' and cc.parent = d.name and cc.contact = %(contact)s))
		    order by d.creation desc limit 1""",
		{
			"last10": last_10_digits(ctx.phone),
			"contact": ctx.contact.name if ctx.contact else "",
			"closed": CLOSED_DEAL_STATUSES,
		},
		pluck=True,
	)
	return rows[0] if rows else None


def _link_deal_customer(deal, ctx):
	"""
	[BR-CRM-004] A caller who is already a Customer has the Deal's "Customer
	in ERPNext" filled in (when the ERPNext CRM integration made that field),
	so the CRM's Deal screen shows whose Deal it is. Never overwrites a
	Customer someone entered there.
	"""
	if ctx.customer and frappe.get_meta("CRM Deal").has_field("erpnext_customer"):
		if not frappe.db.get_value("CRM Deal", deal, "erpnext_customer"):
			frappe.db.set_value("CRM Deal", deal, "erpnext_customer", ctx.customer.name, update_modified=False)


def _get_or_create_deal(ctx):
	"""
	[BR-CRM-004] Reuses the caller's open CRM Deal; creates one only when none
	is open. A new Deal gets the caller's Contact as its primary contact (so
	CRM shows the caller and fills the Deal's number from it); a caller with
	no Contact has the number written onto the Deal directly, since CRM
	Deal's own validate blanks `mobile_no` when there is no Contact.
	"""
	existing = _open_deal(ctx)
	if existing:
		_link_deal_customer(existing, ctx)
		return existing, False
	deal = {
		"doctype": "CRM Deal",
		"status": _settings().deal_status or "Qualification",
	}
	if ctx.contact:
		deal["contacts"] = [{"contact": ctx.contact.name, "is_primary": 1}]
	if ctx.lead:
		deal.update(lead=ctx.lead["name"], lead_name=ctx.lead.get("lead_name"))
	if ctx.customer and frappe.db.exists("CRM Organization", ctx.customer.customer_name):
		deal["organization"] = ctx.customer.customer_name
	elif ctx.customer:
		deal["lead_name"] = ctx.customer.customer_name
	doc = frappe.get_doc(deal).insert(ignore_permissions=True)
	if not last_10_digits(doc.mobile_no) and last_10_digits(ctx.phone):
		frappe.db.set_value("CRM Deal", doc.name, "mobile_no", ctx.phone, update_modified=False)
	_link_deal_customer(doc.name, ctx)
	return doc.name, True


def _settings_price_list(category, customer_group=None):
	"""
	[BR-CRM-006] The Caller Categories fallback list for `category`: the row
	for the caller's own Customer Group if it has a list, else the category's
	default row. Returns None when neither carries a list.
	"""
	rows = _category_rows(category)
	own = next((r for r in rows if customer_group and r.customer_group == customer_group and r.price_list), None)
	default = next((r for r in rows if r.is_default and r.price_list), None)
	row = own or default
	return row.price_list if row else None


def _customer_price_list(customer):
	"""
	[BR-CRM-006] A Customer's price list, from the first source that has one:
	the Customer's own `default_price_list`, its Customer Group's, then the
	Caller Categories fallback for the category its group maps to. Never a
	guess (no Selling Settings default) - (None, None) when none has a list.

	Returns:
		tuple: (price list name | None, source "customer" | "customer_group" | "settings" | None).
	"""
	if customer.default_price_list:
		return customer.default_price_list, "customer"
	group_list = frappe.db.get_value("Customer Group", customer.customer_group, "default_price_list") if customer.customer_group else None
	if group_list:
		return group_list, "customer_group"
	settings_list = _settings_price_list(customer.category, customer.customer_group) if customer.category else None
	if settings_list:
		return settings_list, "settings"
	return None, None


def _price_list_problem(price_list, currency):
	"""
	[BR-CRM-006] Why `price_list` can't be quoted from - disabled, not a
	selling list, or in another currency than the Quotation - or None. An
	unusable list is an error, never a silent switch to another list.
	"""
	pl = frappe.db.get_value("Price List", price_list, ["enabled", "selling", "currency"], as_dict=True)
	if not pl:
		return "does not exist"
	if not pl.enabled:
		return "is disabled"
	if not pl.selling:
		return "is not a selling price list"
	if currency and pl.currency != currency:
		return f"is in {pl.currency}, the quotation is in {currency}"
	return None


def _quote_party(ctx):
	"""
	[BR-CRM-006] Who a voice-agent Quotation is addressed to, and at what
	price list. An existing Customer is quoted as the Customer at their own
	price list (`_customer_price_list`: Customer, then Customer Group, then
	the Caller Categories fallback). A caller with only a CRM Lead is quoted
	through a CRM Deal (ERPNext Quotations accept `CRM Deal`, never
	`CRM Lead`) at the price list their caller category maps to - a category
	with no price list is never quoted by the agent. The list chosen must be
	usable (`_price_list_problem`) or the quote is refused.
	"""
	company_currency = frappe.db.get_value("Company", _quote_company(), "default_currency")

	if ctx.customer:
		price_list, source = _customer_price_list(ctx.customer)
		if not price_list:
			return None, _error(
				"NO_PRICE_LIST",
				"No price list is set for this customer - the team will call back with prices.",
				customer=ctx.customer.name,
			)
		currency = frappe.db.get_value("Customer", ctx.customer.name, "default_currency") or company_currency
		party = frappe._dict(
			quotation_to="Customer",
			party_name=ctx.customer.name,
			customer_group=ctx.customer.customer_group,
			price_list=price_list,
			price_list_source=source,
		)
	elif ctx.lead:
		category = ctx.lead.get("caller_category")
		row = _category_default(category)
		price_list = _settings_price_list(category)
		if not row or not price_list:
			return None, _error(
				"QUOTE_NOT_AVAILABLE",
				"The team will call back with prices for this caller category.",
				caller_category=category,
			)
		currency = company_currency
		party = frappe._dict(
			quotation_to="CRM Deal", party_name=None, customer_group=row.customer_group, price_list=price_list, price_list_source="settings"
		)
	else:
		return None, _error("NOT_ON_RECORD", "Save the caller's name and number (save_request) before quoting.")

	problem = _price_list_problem(party.price_list, currency)
	if problem:
		return None, _error(
			"PRICE_LIST_UNUSABLE",
			"The caller's price list can't be used right now - the team will call back with prices.",
			price_list=party.price_list,
			price_list_source=party.price_list_source,
			reason=problem,
		)
	return party, None


def _check_items(items, party):
	"""Returns (shipping_rule, error)."""
	pack_rows = {r.item_code: r for r in _settings().pack_items}
	missing_price, not_for_group, unavailable = [], [], []
	rules = []
	for row in items:
		item = frappe.db.get_value("Item", row["item_code"], ["disabled", "is_sales_item"], as_dict=True)
		if not item or item.disabled or not item.is_sales_item:
			unavailable.append(row["item_code"])
			continue
		pack = pack_rows.get(row["item_code"])
		if pack:
			if pack.customer_group != party.customer_group:
				not_for_group.append(row["item_code"])
			elif pack.shipping_rule not in rules:
				rules.append(pack.shipping_rule)
		if not frappe.db.exists("Item Price", {"item_code": row["item_code"], "price_list": party.price_list}):
			missing_price.append(row["item_code"])

	if unavailable:
		return None, _error("ITEM_NOT_AVAILABLE", "These items are not for sale.", items=unavailable)
	if not_for_group:
		return None, _error(
			"PACK_NOT_AVAILABLE",
			"These packs are only sold to another customer group.",
			items=not_for_group,
			customer_group=party.customer_group,
		)
	if missing_price:
		return None, _error(
			"PRICE_NOT_FOUND", "No price for these items in the caller's price list.", items=missing_price, price_list=party.price_list
		)
	if len(rules) > 1:
		return None, _error("MIXED_SHIPPING", "These items ship under different shipping rules - quote them separately.", shipping_rules=rules)
	return (rules[0] if rules else None), None


def _apply_pincode(doc, pincode):
	"""
	[BR-CRM-006] Same in-state/out-state decision as `quotation_gst.apply_gst`
	makes from a lead's Address line, for a pincode given explicitly.
	"""
	state = quotation_gst.state_from_pincode(pincode)
	home_code = (doc.get("company_gstin") or "")[:2] or frappe.db.get_value("Address", doc.company_address, "gst_state_number") or "33"
	in_state = state == "Tamil Nadu" if home_code == "33" else False
	template = quotation_gst._template(doc.company, "In-State" if in_state else "Out-State")
	if template:
		doc.taxes_and_charges = template
	if state:
		quotation_gst._set_place_of_supply(doc, state)


def _template_for_place_of_supply(doc):
	"""In-State/Out-State Sales Taxes template matching `doc.place_of_supply` ("36-Telangana")."""
	home_code = (doc.get("company_gstin") or "")[:2]
	place = doc.get("place_of_supply") or ""
	if not home_code or not place[:2].isdigit():
		return doc.taxes_and_charges
	return quotation_gst._template(doc.company, "In-State" if place[:2] == home_code else "Out-State") or doc.taxes_and_charges


def _has_gst_rows(doc):
	return any(t.charge_type != "Actual" for t in doc.get("taxes") or [])


def _gst_type(company, account_head):
	try:
		from india_compliance.gst_india.utils import get_gst_accounts_by_type

		accounts = get_gst_accounts_by_type(company, "Output", throw=False) or {}
		for kind in ("cgst", "sgst", "igst", "cess"):
			if accounts.get(f"{kind}_account") == account_head:
				return kind.upper()
	except Exception:
		pass
	for kind in ("CGST", "SGST", "IGST", "CESS"):
		if kind in (account_head or "").upper():
			return kind
	return account_head


def _quote_response(doc, created, deal):
	detail_rates = {}
	for d in doc.get("item_wise_tax_details") or []:
		detail_rates.setdefault(d.tax_row, flt(d.rate))
	taxes, shipping = [], 0.0
	for t in doc.taxes:
		if t.charge_type == "Actual":
			shipping += flt(t.tax_amount)
			continue
		taxes.append(
			{
				"type": _gst_type(doc.company, t.account_head),
				"rate": detail_rates.get(t.name, flt(t.rate)),
				"amount": flt(t.tax_amount),
			}
		)
	return {
		"allowed": True,
		"status": "quoted",
		"quotation": doc.name,
		"created": created,
		"deal": deal,
		"price_list": doc.selling_price_list,
		"place_of_supply": doc.get("place_of_supply"),
		"items": [
			{"item_code": i.item_code, "item_name": i.item_name, "qty": i.qty, "rate": i.rate, "amount": i.amount}
			for i in doc.items
		],
		"net_total": doc.net_total,
		"taxes": taxes,
		# [BR-CRM-006] One GST figure for the agent to say ("GST at 5%: ₹23.81"),
		# so it never adds CGST and SGST itself: the GST rows' rates and
		# amounts summed - each row is already rounded by the Quotation, and the
		# sum is rounded to the precision of its own tax total.
		"gst_percent": flt(sum(t["rate"] for t in taxes), 2),
		"gst_amount": flt(sum(t["amount"] for t in taxes), doc.precision("total_taxes_and_charges")),
		"shipping": shipping,
		"rounding_adjustment": doc.rounding_adjustment,
		"grand_total": doc.grand_total,
		"rounded_total": doc.rounded_total,
		"total_to_say": doc.rounded_total or doc.grand_total,
	}


def _find_draft_quotation(quotation_to, party_name, user):
	return frappe.db.get_value(
		"Quotation",
		{
			"quotation_to": quotation_to,
			"party_name": party_name,
			"docstatus": 0,
			"owner": user,
			"transaction_date": nowdate(),
		},
		"name",
		order_by="creation desc",
	)


def _upsert_quote(ctx, items, ship_to_pincode=None, address_name=None):
	"""
	[BR-CRM-006] Creates (or updates today's) draft Quotation for the caller
	and returns its own saved totals - so the figures the agent reads out are,
	by construction, the figures on the document.

	[BR-CRM-008] With `address_name` (one of the caller's own saved
	Addresses), that Address becomes the Quotation's `shipping_address_name`
	and wins over `ship_to_pincode`. For a Customer, India Compliance then
	works out the place of supply exactly as it does in Desk (which address
	it reads follows Accounts Settings > "Determine Address Tax Category
	From"). For a CRM Deal quotation India Compliance does not read the
	address at all, so the Address's own pincode drives the same
	in-state/out-state decision `quotation_gst` makes.

	Runs inside a savepoint: any failure after the document is written (e.g.
	GST could not be determined) leaves nothing behind.
	"""
	address = None
	if address_name:
		address, err = _owned_address(ctx, address_name)
		if err:
			return err
		ship_to_pincode = address.pincode
	party, err = _quote_party(ctx)
	if err:
		return err
	shipping_rule, err = _check_items(items, party)
	if err:
		return err

	frappe.db.savepoint("voice_agent_quote")
	try:
		deal, _created_deal = _get_or_create_deal(ctx)
		if party.quotation_to == "CRM Deal":
			party.party_name = deal

		user = frappe.session.user
		existing = _find_draft_quotation(party.quotation_to, party.party_name, user)
		if existing:
			doc = frappe.get_doc("Quotation", existing)
			doc.items = []
			doc.taxes = []
			# A re-quote may be for a different address/state - let GST be worked out afresh.
			doc.taxes_and_charges = None
			doc.place_of_supply = None
		else:
			from frappe.contacts.doctype.address.address import get_company_address

			company = _quote_company()
			doc = frappe.new_doc("Quotation")
			doc.update(
				{
					"quotation_to": party.quotation_to,
					"party_name": party.party_name,
					"company": company,
					"company_address": get_company_address(company).company_address,
					"order_type": "Sales",
				}
			)
			if doc.meta.has_field("crm_deal"):
				doc.crm_deal = deal
		doc.selling_price_list = party.price_list
		doc.contact_mobile = ctx.phone
		doc.shipping_rule = shipping_rule
		doc.shipping_address_name = address.name if address else None
		for row in items:
			doc.append("items", row)
		if ship_to_pincode and not (address and party.quotation_to == "Customer"):
			_apply_pincode(doc, str(ship_to_pincode).strip())

		doc.save(ignore_permissions=True)
		# India Compliance works out the place of supply during validate, but
		# on a server-side save it neither copies the GST rows nor re-picks the
		# template when the place of supply comes from a different state than
		# the billing address (the Desk form does both client-side). So pick
		# the In-State/Out-State template matching the place of supply it
		# decided, and save again - quotation_gst.apply_gst (before_validate)
		# then fills the rows from it.
		# Only when the place of supply rests on a real address or pincode -
		# otherwise it is just the company's own state, and the caller must be
		# asked for a pincode (PINCODE_REQUIRED below), never quoted on a guess.
		grounded = doc.get("customer_address") or doc.get("shipping_address_name") or ship_to_pincode
		if not _has_gst_rows(doc) and grounded:
			template = _template_for_place_of_supply(doc)
			if template:
				doc.taxes_and_charges = template
				doc.save(ignore_permissions=True)

		if not _has_gst_rows(doc):
			frappe.db.rollback(save_point="voice_agent_quote")
			if not ship_to_pincode:
				return _error("PINCODE_REQUIRED", "Ask for the delivery pincode so GST can be worked out.")
			return _error("TAX_NOT_DETERMINED", "GST could not be worked out for this pincode.", pincode=ship_to_pincode)
	except Exception:
		frappe.db.rollback(save_point="voice_agent_quote")
		raise

	response = _quote_response(doc, not existing, deal)
	# Which source the list came from - for logging; the agent doesn't speak it.
	response["price_list_source"] = party.price_list_source
	return response


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def upsert_quote(
	phone: str | None = None,
	key: str | None = None,
	items: str | list | None = None,
	ship_to_pincode: str | None = None,
	address_name: str | None = None,
	address: str | None = None,
	city: str | None = None,
	state: str | None = None,
	pincode: str | None = None,
):
	"""
	Business Purpose: [BR-CRM-006] Creates or updates the caller's draft
	Quotation for `items` and returns the numbers the agent reads aloud -
	net_total (before any charges), GST lines, shipping (from the Shipping
	Rule) and the rounded total - never computed by the agent itself.

	The caller must already be on record (a CRM Lead from save_request, or an
	existing Customer). Repeat calls on the same day update the same draft.

	Args:
		phone (str): The caller's number, any spelling.
		key (str): Must match Sarvam Voice Agent Settings.webhook_secret.
		items (list | JSON str): [{"item_code": ..., "qty": ...}].
		ship_to_pincode (str | None): Delivery pincode, when the caller's
			Lead has no Address line yet / the Customer has no address.
		address_name (str | None): One of the caller's saved Addresses (as
			returned in caller_context's `addresses`); wins over
			ship_to_pincode. Not the caller's -> ADDRESS_NOT_ON_RECORD.
		address, city, state, pincode (str | None): [BR-CRM-008] A new
			delivery address the caller spoke (no address_name). Saved as a
			Shipping Address on their Customer, else their Lead (same line +
			pincode reuses it) and set as the Quotation's shipping address;
			a failed quote saves nothing. Missing city/pincode: quoted on the
			pincode alone, with an ADDRESS_NOT_SAVED warning.

	Returns:
		dict: {allowed, status: "quoted", quotation, created, deal, items,
		net_total, taxes: [{type, rate, amount}], shipping,
		rounding_adjustment, grand_total, rounded_total, total_to_say}, or
		{allowed, status: "error", error: <CODE>, message}. With a spoken
		address, also `address` (the saved Address) and `warnings`.
	"""
	_check_webhook_key(key)
	gate = evaluate(phone)
	if not gate["allowed"]:
		return gate
	parsed, problem = _parse_items(items)
	if problem or not parsed:
		return _error("INVALID_ITEMS", problem or "items is empty")
	with _as_automation_user():
		ctx = _resolve(phone)
		owner = _address_owner(ctx)
		if address_name or not (address or "").strip() or not owner:
			return _upsert_quote(ctx, parsed, ship_to_pincode, address_name)

		pin_in_text = _PIN.search(address)
		pin = pincode or ship_to_pincode or (pin_in_text.group() if pin_in_text else None)
		title = (ctx.customer.customer_name if ctx.customer else (ctx.lead or {}).get("lead_name")) or ctx.phone
		frappe.db.savepoint("voice_agent_quote_address")
		try:
			saved, warning = _save_caller_address(owner, title, address, city, state, pin)
		except _RequestRefused as e:
			frappe.db.rollback(save_point="voice_agent_quote_address")
			return e.result
		result = _upsert_quote(ctx, parsed, pin, saved)
		if result.get("status") != "quoted":
			frappe.db.rollback(save_point="voice_agent_quote_address")
			return result
		return {**result, "address": saved, "warnings": [warning] if warning else []}


# --------------------------------------------------------------------------
# 4. Save request  [BR-CRM-004]
# --------------------------------------------------------------------------

_PIN = re.compile(r"(?<!\d)[1-9]\d{5}(?!\d)")


def _description_lines(caller_type, store_type, area, notes, address, whatsapp_number, ship_to_pincode):
	if ship_to_pincode and not _PIN.search(address or ""):
		address = f"{address}, {ship_to_pincode}" if address else str(ship_to_pincode)
	lines = [
		("Category", caller_type),
		("Store type", store_type),
		("Area", area),
		("Requirement", notes),
		# quotation_gst reads the pincode from this exact "Address:" line.
		("Address", address),
		("WhatsApp", whatsapp_number),
	]
	return "\n".join(f"{label}: {value}" for label, value in lines if value)


def _upsert_callback_task(reference_doctype, reference_name, title, description):
	"""
	[BR-CRM-004] One open callback task per record per day - a repeat save
	updates it. A task with no record to hang on (a spoken callback number
	that matches only a Customer) is matched on its title instead.
	"""
	settings = _settings()
	filters = {
		"status": ("in", OPEN_TASK_STATUSES),
		"owner": frappe.session.user,
		"creation": (">=", nowdate()),
	}
	if reference_name:
		filters.update(reference_doctype=reference_doctype, reference_docname=reference_name)
	else:
		filters.update(reference_docname=("is", "not set"), title=title)
	existing = frappe.db.get_value("CRM Task", filters, "name")
	if existing:
		frappe.db.set_value("CRM Task", existing, {"title": title, "description": description})
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": title,
				"description": description,
				"reference_doctype": reference_doctype,
				"reference_docname": reference_name,
				"assigned_to": settings.callback_task_assignee,
				"priority": settings.callback_task_priority or "High",
				"status": "Todo",
				"start_date": nowdate(),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _duplicate_message(lead):
	return DUPLICATE_LEAD_MESSAGE.format(
		name=lead["name"],
		lead_name=lead.get("lead_name") or "",
		mobile_no=lead.get("mobile_no") or "",
		status=lead.get("status") or "",
	)


def _parse_token(message, token):
	"""`DUPLICATE_LEAD: name=X; ...` -> {"name": "X", ...}"""
	body = (message or "").split(f"{token}:", 1)[-1]
	return dict(part.strip().split("=", 1) for part in body.split(";") if "=" in part)


class _RequestRefused(Exception):
	"""Aborts save_request after writes have started; the caller rolls back and returns `result`."""

	def __init__(self, result):
		super().__init__(result.get("error"))
		self.result = result


def _save_caller_address(owner, title, line, city, state, pincode):
	"""
	[BR-CRM-008] A delivery address the caller spoke, saved as a real
	Shipping `Address` linked (Dynamic Link) to `owner` - their Customer, or
	for a caller with no Customer their CRM Lead (the same mechanism
	`contact_lead_link` uses to link a Lead's Contact). A repeat of the same
	line + pincode reuses the existing Address. A Lead's address becomes its
	preferred shipping address; a Customer's preferred one is left as staff
	set it - this address is chosen on the quote itself.

	Returns:
		tuple: (address name, None) or (None, warning) when a field Frappe's
		Address requires is missing - the request is still saved then, with
		the address kept only as text.
	"""
	state = state or (quotation_gst.state_from_pincode(pincode) if pincode else None)
	missing = [field for field, value in (("city", city), ("pincode", pincode), ("state", state)) if not value]
	if missing:
		return None, f"ADDRESS_NOT_SAVED: missing {', '.join(missing)}"

	for existing in _linked_addresses(owner):
		if (existing.address_line1 or "").strip().lower() == line.strip().lower() and existing.pincode == pincode:
			return existing.name, None

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_type": "Shipping",
				"address_line1": line.strip(),
				"city": city.strip(),
				"state": state,
				"pincode": pincode,
				"country": frappe.db.get_value("Company", _quote_company(), "country"),
				"is_shipping_address": int(owner[0] == "CRM Lead"),
				"links": [{"link_doctype": owner[0], "link_name": owner[1]}],
			}
		).insert(ignore_permissions=True)
	except frappe.ValidationError as e:
		if "CALLER_BLOCKED:" in str(e):
			raise
		raise _RequestRefused(
			_error("ADDRESS_INVALID", "That address could not be saved - check the city, state and pincode.", detail=str(e))
		) from e
	return doc.name, None


def _spoken_mobile(number):
	"""[BR-CRM-004] A spoken callback number as +91 and ten digits - an Indian mobile only - else None."""
	canonical = normalise((number or "").strip())
	if canonical and canonical.startswith("+91") and MOBILE.fullmatch(canonical[3:]):
		return canonical
	return None


def _save_request(
	ctx, *, name, caller_type, organization, items, address, whatsapp_number, notes, store_type, area,
	ship_to_pincode, address_name, city, state, pincode, callback_only=False,
):
	result = {
		"allowed": True, "status": "saved", "lead": None, "deal": None, "quotation": None, "task": None,
		"quote": None, "warnings": [], "message": "", "address": None,
		"number_source": "callback_number" if callback_only else "phone",
	}

	# [BR-CRM-008] A saved Address must be the caller's own - checked before anything is written.
	saved_address = None
	if address_name:
		saved_address, err = _owned_address(ctx, address_name)
		if err:
			return err
		address, pincode, city, state = _address_text(saved_address), saved_address.pincode, saved_address.city, saved_address.state
		result["address"] = saved_address.name
	pin_in_text = _PIN.search(address or "")
	pincode = pincode or ship_to_pincode or (pin_in_text.group() if pin_in_text else None)

	category = (caller_type or "").strip().lower() or None
	# [BR-CRM-005] The spoken category only matters when there is no Customer
	# group to go by: a Customer whose group maps to a configured category is
	# already classified, whatever the caller said.
	has_usable_group = bool(ctx.customer and ctx.customer.customer_group and ctx.customer.category)
	if category and not has_usable_group:
		if not _category_rows(category):
			result["warnings"].append(f"UNKNOWN_CATEGORY: {caller_type}")
		elif not _category_default(category):
			result["warnings"].append(f"CUSTOMER_GROUP_NEEDS_REVIEW: {category}")

	description = _description_lines(caller_type, store_type, area, notes, address, whatsapp_number, pincode)
	if callback_only:
		# The Lead's own record says the number wasn't seen on the line.
		description = "\n".join(filter(None, [f"Number: {ctx.phone} (given by the caller, not the line)", description]))
	display_name = name or (ctx.customer.customer_name if ctx.customer else None) or (ctx.lead or {}).get("lead_name")

	if ctx.lead:
		# [BR-CRM-001] Never a second lead for the same number - the existing one is the answer.
		result.update(status="duplicate", lead=ctx.lead["name"], message=_duplicate_message(ctx.lead))
	elif not ctx.customer:
		if not (name or "").strip():
			return _error("NAME_REQUIRED", "Ask for the caller's name before saving.")
		settings = _settings()
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": name.strip(),
				"mobile_no": ctx.phone,
				"organization": organization,
				"status": "New",
				"lead_owner": settings.default_lead_owner or frappe.session.user,
				# Keeps the "Address:" line quotation_gst.apply_gst and staff views read.
				"company_description": description,
				"custom_caller_category": category,
				"custom_store_type": store_type,
			}
		).insert(ignore_permissions=True)
		ctx.lead = _find_lead(last_10_digits(ctx.phone))
		result.update(lead=lead.name, message="Saved.")

	# [BR-CRM-008] A new address the caller gives is saved as a real Address -
	# on their Customer if they have one, else on their Lead.
	owner = _address_owner(ctx)
	if not saved_address and (address or "").strip() and owner:
		new_address, warning = _save_caller_address(owner, display_name or ctx.phone, address, city, state, pincode)
		if warning:
			result["warnings"].append(warning)
		else:
			result["address"] = new_address

	quoted = False
	if callback_only:
		# [BR-CRM-004] A spoken number is unverified: callback only - no quote, no Deal.
		if items:
			result["warnings"].append("NOT_QUOTED: callback number given by the caller - the team will quote on the callback")
	elif items:
		quote = _upsert_quote(ctx, items, pincode, result["address"])
		result["quote"] = quote
		if quote.get("status") == "quoted":
			quoted = True
			result.update(quotation=quote["quotation"], deal=quote["deal"])
		else:
			result["warnings"].append(f"{quote['error']}: {quote['message']}")
	elif ctx.customer:
		# [BR-CRM-004] An existing customer's request always opens (or reuses) a Deal.
		result["deal"], _ = _get_or_create_deal(ctx)

	# [BR-CRM-004] Everything not fully handled by a quote gets a callback task.
	if not quoted or not ctx.customer:
		if ctx.lead:
			ref = ("CRM Lead", ctx.lead["name"])
		elif callback_only:
			# A Customer with no Lead: their open Deal if they have one, never a new one.
			open_deal = _open_deal(ctx)
			ref = ("CRM Deal", open_deal) if open_deal else (None, None)
			result["deal"] = open_deal
		else:
			ref = ("CRM Deal", result["deal"] or _get_or_create_deal(ctx)[0])
			result["deal"] = ref[1]
		flags = "\n".join(result["warnings"])
		lines = [f"Phone: {ctx.phone}", description, flags]
		if callback_only:
			asked = ", ".join(f"{i['item_code']} x {i['qty']}" for i in items or [])
			lines = [
				f"{CALLBACK_NUMBER_NOTE} {notes or ''}".strip(),
				f"Customer: {ctx.customer.customer_name}" if ctx.customer else None,
				f"Items asked for: {asked}" if asked else None,
				*lines,
			]
		task_description = "\n".join(filter(None, lines))
		result["task"] = _upsert_callback_task(*ref, f"{CALLBACK_TASK_TITLE_PREFIX} {display_name or ctx.phone}", task_description)

	if result["status"] == "duplicate":
		result["note"] = "A lead already exists for this number - a new lead was not created; the request was added to the existing lead."
	return result


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def save_request(
	phone: str | None = None,
	key: str | None = None,
	name: str | None = None,
	caller_type: str | None = None,
	organization: str | None = None,
	items: str | list | None = None,
	address: str | None = None,
	whatsapp_number: str | None = None,
	notes: str | None = None,
	store_type: str | None = None,
	area: str | None = None,
	ship_to_pincode: str | None = None,
	address_name: str | None = None,
	city: str | None = None,
	state: str | None = None,
	pincode: str | None = None,
	callback_number: str | None = None,
):
	"""
	Business Purpose: [BR-CRM-004] Saves everything the caller asked for in
	one transaction, replacing the agent's chain of create calls:

	- New caller: a CRM Lead (category, store type, address etc. recorded),
	  a callback CRM Task, and - when they asked for items and their category
	  is quotable - a CRM Deal and draft Quotation.
	- Caller with an existing CRM Lead: no new Lead (status "duplicate", the
	  existing Lead's id and the DUPLICATE_LEAD token), the request recorded
	  on a callback Task against that Lead (and quoted if they asked for items).
	- Existing Customer: a CRM Deal and draft Quotation for the items; a
	  callback Task if there were no items or the quote couldn't be made.

	[BR-CRM-008] `address_name` (one of the caller's saved Addresses from
	caller_context) is used instead of a spoken address and wins over
	`address`/`ship_to_pincode`; one that isn't the caller's returns
	ADDRESS_NOT_ON_RECORD and saves nothing. A spoken `address` (+ `city`,
	`state`, `pincode`) from a caller with no Customer is saved as a Shipping
	Address linked to their CRM Lead.

	[BR-CRM-004] `callback_number` - the number the caller said - is used
	only when `phone` (the line's number) is blank, and ignored otherwise.
	It must be an Indian mobile (saved as +91 and ten digits; anything else
	is CALLBACK_NUMBER_INVALID) and goes through the same caller gate as
	`phone`. Such a save is a callback only: the Lead is created (or the
	existing one matched, same duplicate rules) with a callback Task whose
	notes start "Callback request (number given by the caller, not the
	line):" - never a quote or a Deal.

	All-or-nothing: if any write fails, nothing is kept.

	Returns:
		dict: {allowed, status: "saved" | "duplicate" | "blocked" | "error",
		lead, deal, quotation, task, quote, warnings, message, address,
		number_source: "phone" | "callback_number"}.
	"""
	_check_webhook_key(key)
	callback_only = False
	if not last_10_digits(phone) and (callback_number or "").strip():
		spoken = _spoken_mobile(callback_number)
		if not spoken:
			return _error(
				"CALLBACK_NUMBER_INVALID",
				"That doesn't sound like a 10-digit Indian mobile number - ask the caller to say it again.",
				callback_number=callback_number,
			)
		phone, callback_only = spoken, True
	gate = evaluate(phone)
	if not gate["allowed"]:
		return {**gate, "status": "blocked", "lead": None, "deal": None, "quotation": None, "task": None}
	if not last_10_digits(phone):
		return _error("PHONE_REQUIRED", "Ask for the caller's mobile number before saving.")

	parsed, problem = _parse_items(items)
	if problem:
		return _error("INVALID_ITEMS", problem)

	with _as_automation_user():
		frappe.db.savepoint("voice_agent_save_request")
		try:
			return _save_request(
				_resolve(phone),
				name=name,
				caller_type=caller_type,
				organization=organization,
				items=parsed,
				address=address,
				whatsapp_number=whatsapp_number,
				notes=notes,
				store_type=store_type,
				area=area,
				ship_to_pincode=ship_to_pincode,
				address_name=address_name,
				city=city,
				state=state,
				pincode=pincode,
				callback_only=callback_only,
			)
		except _RequestRefused as refused:
			frappe.db.rollback(save_point="voice_agent_save_request")
			return refused.result
		except frappe.DuplicateEntryError as e:
			# [BR-CRM-001] Another request created the Lead between our lookup and insert.
			frappe.db.rollback(save_point="voice_agent_save_request")
			message = str(e)
			if "DUPLICATE_LEAD:" not in message:
				raise
			return {
				"allowed": True,
				"status": "duplicate",
				"lead": _parse_token(message, "DUPLICATE_LEAD").get("name"),
				"deal": None,
				"quotation": None,
				"task": None,
				"message": message,
			}
		except frappe.ValidationError as e:
			frappe.db.rollback(save_point="voice_agent_save_request")
			message = str(e)
			if "CALLER_BLOCKED:" not in message:
				raise
			parsed_token = _parse_token(message, "CALLER_BLOCKED")
			return {
				"allowed": False,
				"status": "blocked",
				"reason": parsed_token.get("reason"),
				"lead": None,
				"deal": None,
				"quotation": None,
				"task": None,
				"message": message,
			}
		except Exception:
			frappe.db.rollback(save_point="voice_agent_save_request")
			raise


# --------------------------------------------------------------------------
# 5. Transfer target  [BR-TEL-006]
# --------------------------------------------------------------------------


def _now(tz):
	return datetime.now(tz)


WEEK = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY_NAMES = dict(zip(WEEK, ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")))


def _transfer_days(settings):
	return [d.strip()[:3].title() for d in (settings.transfer_days or "").split(",") if d.strip()]


def _spoken_time(t):
	"""10:00 -> "10 AM", 10:30 -> "10:30 AM", 00:00 -> "12 AM", 12:00 -> "12 PM"."""
	hour = t.hour % 12 or 12
	suffix = "AM" if t.hour < 12 else "PM"
	return f"{hour} {suffix}" if t.minute == 0 else f"{hour}:{t.minute:02d} {suffix}"


def _spoken_list(parts):
	return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


def _spoken_days(days):
	"""
	Consecutive days collapse into a range ("Monday to Saturday"), others are
	listed ("Monday, Wednesday and Friday"); all seven are "every day".
	"""
	present = [d for d in WEEK if d in set(days)]
	if not present:
		return ""
	if len(present) == len(WEEK):
		return "every day"
	runs, run = [], [present[0]]
	for day in present[1:]:
		if WEEK.index(day) == WEEK.index(run[-1]) + 1:
			run.append(day)
		else:
			runs.append(run)
			run = [day]
	runs.append(run)
	parts = []
	for r in runs:
		if len(r) >= 3:
			parts.append(f"{DAY_NAMES[r[0]]} to {DAY_NAMES[r[-1]]}")
		else:
			parts.extend(DAY_NAMES[d] for d in r)
	return _spoken_list(parts)


def _hours_text(settings):
	"""
	[BR-TEL-006] The transfer hours as the agent says them - "10 AM to 8 PM,
	Monday to Saturday" - built from the settings, so a change there changes
	what the agent says. 00:00 to 23:59 is "all day".
	"""
	start = get_time(settings.transfer_start_time or "00:00:00")
	end = get_time(settings.transfer_end_time or "23:59:59")
	all_day = (start.hour, start.minute) == (0, 0) and (end.hour, end.minute) == (23, 59)
	times = "all day" if all_day else f"{_spoken_time(start)} to {_spoken_time(end)}"
	days = _spoken_days(_transfer_days(settings))
	return f"{times}, {days}" if days else times


def _transfer_window_open(settings):
	tz = ZoneInfo(settings.transfer_timezone or "Asia/Kolkata")
	now = _now(tz)
	days = _transfer_days(settings)
	if now.strftime("%a") not in days:
		return False, now
	start = get_time(settings.transfer_start_time or "00:00:00")
	end = get_time(settings.transfer_end_time or "23:59:59")
	return start <= now.time().replace(microsecond=0) < end, now


# --- Routing: who takes the call  [BR-TEL-006] -------------------------------
#
# Every decision transfer_target makes is one Sarvam Transfer Attempt row; the
# rows are the whole state - an executive is busy while they have a Routed or
# Connected row younger than the busy timeout, the round-robin pointer is the
# executive on the newest row that routed a call, and sticky routing reads the
# rows that connected. Executives answer on personal phones, so there is no
# live telephony state to ask.

ATTEMPT_DOCTYPE = "Sarvam Transfer Attempt"
EXECUTIVE_DOCTYPE = "Sarvam Transfer Executive"
ROUTED, CONNECTED, NOT_CONNECTED, ENDED, EXPIRED, REFUSED = ("Routed", "Connected", "Not connected", "Ended", "Expired", "Refused")
BUSY_STATUSES = (ROUTED, CONNECTED)
# A row whose call reached the executive - what sticky routing remembers.
TOOK_CALL_STATUSES = (CONNECTED, ENDED)
# The field's own default; an existing Single reads 0 until it is saved.
DEFAULT_BUSY_TIMEOUT_MINUTES = 5
DEFAULT_ORDERABLE_ITEM_GROUP = "Products"
# [BR-CRM-006] Items whose code or name contains this are never offered by orderable_items.
NOT_ORDERABLE_TEXT = "sample"
MANAGER_ROLES = ("System Manager", "Sales Manager")


def _busy_timeout(settings):
	return cint(settings.busy_timeout_minutes) or DEFAULT_BUSY_TIMEOUT_MINUTES


def _name_key(name):
	return " ".join(re.sub(r"[^0-9a-z]+", " ", (name or "").lower()).split())


def _executive_rows(lock=False):
	"""
	Enabled executives that have a number, in table (round-robin) order -
	read from the database, not the cached settings, so an On Break tick is
	seen at once. With `lock`, every executive row is locked FOR UPDATE until
	the request's transaction ends: two calls routing at the same moment
	queue here, and the second sees the first one's Routed row.

	Every ledger read after the lock is a locking read (FOR UPDATE / LOCK IN
	SHARE MODE): under REPEATABLE READ a plain SELECT would still read the
	snapshot taken before the lock was granted - before the first call's
	Routed row was committed - and hand out the same executive twice.
	"""
	rows = frappe.db.sql(
		f"""select name, idx, executive_name, phone, user, enabled, on_break, aliases
		    from `tab{EXECUTIVE_DOCTYPE}`
		    where parenttype = %(settings)s and parent = %(settings)s and parentfield = 'transfer_executives'
		    order by idx{' for update' if lock else ''}""",
		{"settings": SARVAM_SETTINGS_DOCTYPE},
		as_dict=True,
	)
	return [r for r in rows if cint(r.enabled) and (r.phone or "").strip()]


def _busy_cutoff(timeout):
	return add_to_date(now_datetime(), minutes=-timeout)


def _append_log(text, line):
	stamp = now_datetime().strftime("%Y-%m-%d %H:%M:%S")
	return f"{text}\n{stamp} {line}" if text else f"{stamp} {line}"


def _close_attempt(name, status, note, ended_at=None):
	"""Moves one attempt to `status` (and ended_at), appending `note` to its decision log."""
	log = frappe.db.get_value(ATTEMPT_DOCTYPE, name, "decision_log")
	values = {"status": status, "decision_log": _append_log(log, note)}
	if ended_at:
		values["ended_at"] = ended_at
	frappe.db.set_value(ATTEMPT_DOCTYPE, name, values)


def expire_transfer_attempts(timeout=None):
	"""
	[BR-TEL-006] Frees executives whose call-end never told us otherwise: a
	Routed row older than the busy timeout becomes Expired, a Connected one
	Ended, with ended_at = routed_at + timeout. The busy check itself ignores
	old rows anyway - this keeps the rows' statuses true for the log and the
	busy list. Runs from transfer_target and the scheduler (every 5 minutes).
	"""
	timeout = timeout or _busy_timeout(_settings())
	for old, new in ((ROUTED, EXPIRED), (CONNECTED, ENDED)):
		for row in frappe.db.sql(
			f"select name, routed_at from `tab{ATTEMPT_DOCTYPE}` where status = %(old)s and routed_at < %(cutoff)s for update",
			{"old": old, "cutoff": _busy_cutoff(timeout)},
			as_dict=True,
		):
			_close_attempt(row.name, new, f"{new}: no call end within {timeout} minutes", add_to_date(row.routed_at, minutes=timeout))


def _busy_since(timeout):
	"""
	{executive_name: when their open attempt was routed}. The busy check
	fails open: if the ledger can't be read, everyone is treated as free
	(and the error logged) - a wrong "free" costs one unanswered transfer,
	which the agent already turns into a callback.
	"""
	try:
		rows = frappe.db.sql(
			f"""select executive, min(routed_at) as since from `tab{ATTEMPT_DOCTYPE}`
			    where status in %(busy)s and routed_at >= %(cutoff)s and ifnull(executive, '') != ''
			    group by executive lock in share mode""",
			{"busy": BUSY_STATUSES, "cutoff": _busy_cutoff(timeout)},
			as_dict=True,
		)
		return {r.executive: r.since for r in rows}
	except Exception:
		frappe.log_error(title="Sarvam transfer: busy ledger unreadable, treating everyone as free")
		return {}


def _executive_names(executive):
	aliases = re.split(r"[,\n;]", executive.aliases or "")
	return {k for k in (_name_key(n) for n in [executive.executive_name, *aliases]) if k}


def _match_executive(spoken, executives):
	"""
	The executive the caller named: their name or an alias equal to what was
	said, ignoring case and punctuation; else one whose name or alias is a
	whole word of it ("Kalpana madam"). Two executives answering to the same
	words is no match - never a guess.
	"""
	key = _name_key(spoken)
	if not key:
		return None
	exact = [e for e in executives if key in _executive_names(e)]
	if exact:
		return exact[0] if len(exact) == 1 else None
	words = f" {key} "
	partial = [e for e in executives if any(f" {n} " in words for n in _executive_names(e))]
	return partial[0] if len(partial) == 1 else None


def _sticky_executive(ctx, executives, notes):
	"""
	[BR-TEL-006] The executive on the caller's newest attempt that connected
	(matched by their Lead, Contact or Customer), else the Lead's owner or
	the Customer's account manager when that user is an enabled executive.
	"""
	by_name = {e.executive_name: e for e in executives}
	keys = {
		"lead": ctx.lead["name"] if ctx.lead else None,
		"contact": ctx.contact["name"] if ctx.contact else None,
		"customer": ctx.customer.name if ctx.customer else None,
	}
	keys = {k: v for k, v in keys.items() if v}
	if keys:
		rows = frappe.db.sql(
			f"""select name, executive from `tab{ATTEMPT_DOCTYPE}`
			    where status in %(took)s and ({' or '.join(f'{k} = %({k})s' for k in keys)})
			    order by creation desc limit 1 lock in share mode""",
			{"took": TOOK_CALL_STATUSES, **keys},
			as_dict=True,
		)
		if rows and rows[0].executive in by_name:
			notes.append(f"sticky: {rows[0].executive} took this caller's last transferred call ({rows[0].name})")
			return by_name[rows[0].executive]
		if rows:
			notes.append(f"sticky: last transferred call went to {rows[0].executive}, no longer an enabled executive")

	by_user = {e.user: e for e in executives if e.user}
	owners = [
		("lead owner", ctx.lead.get("lead_owner") if ctx.lead else None),
		("account manager", frappe.db.get_value("Customer", ctx.customer.name, "account_manager") if ctx.customer else None),
	]
	for label, user in owners:
		if user and user in by_user:
			notes.append(f"sticky: no transferred call on record; {label} {user} is {by_user[user].executive_name}")
			return by_user[user]
	notes.append("sticky: no transferred call on record and no owner who is an executive")
	return None


def _round_robin(executives, unavailable, notes):
	"""
	[BR-TEL-006] The first free executive after the one on the newest attempt
	that routed a call (refusals don't move the pointer), wrapping round the
	table; from the top when that executive is no longer in it.
	"""
	last = frappe.db.sql(
		f"""select executive from `tab{ATTEMPT_DOCTYPE}`
		    where status != %(refused)s and ifnull(executive, '') != ''
		    order by creation desc limit 1 lock in share mode""",
		{"refused": REFUSED},
		pluck=True,
	)
	last = last[0] if last else None
	names = [e.executive_name for e in executives]
	start = names.index(last) + 1 if last in names else 0
	for e in executives[start:] + executives[:start]:
		if e.executive_name not in unavailable:
			notes.append(f"round robin: after {last or 'nobody'} -> {e.executive_name}")
			return e
	return None


def _write_attempt(attempt, notes):
	"""Inserts the decision's row; the request commits it (a GET would otherwise be rolled back)."""
	doc = frappe.get_doc(
		{"doctype": ATTEMPT_DOCTYPE, **attempt, "routed_at": now_datetime(), "decision_log": _append_log("", "; ".join(notes))}
	).insert(ignore_permissions=True)
	frappe.local.flags.commit = True
	return doc.name


def _route(phone, requested, interaction_id):
	settings = _settings()
	hours_text = _hours_text(settings)
	response = {
		"allowed": True, "open": False, "target": None, "target_name": None, "executive": None, "routed_by": None,
		"then": [], "then_names": [], "decision": "CALLBACK", "available": [], "attempt": None, "hours_text": hours_text,
	}
	attempt = frappe._dict(
		caller_phone=_canonical(phone), interaction_id=(interaction_id or "").strip() or None, requested_name=requested or None
	)
	notes = [f"asked for {requested!r}" if requested else "no executive named"]

	def refuse(reason, note, **extra):
		notes.append(note)
		name = _write_attempt({**attempt, "status": REFUSED, "refused_reason": reason}, notes)
		return {**response, "reason": reason, "attempt": name, **extra}

	is_open, now = _transfer_window_open(settings)
	if not is_open:
		return refuse("outside_hours", f"outside transfer hours ({hours_text}) at {now:%a %H:%M}", checked_at=now.isoformat(timespec="minutes"))

	ctx = _resolve(phone)
	attempt.update(
		lead=ctx.lead["name"] if ctx.lead else None,
		contact=ctx.contact["name"] if ctx.contact else None,
		customer=ctx.customer.name if ctx.customer else None,
	)
	if cint(settings.transfer_known_callers_only) and not (ctx.lead or ctx.contact or ctx.customer):
		return refuse("unknown_caller", "caller not on record")

	# From here to the commit, one routing decision at a time.
	timeout = _busy_timeout(settings)
	executives = _executive_rows(lock=True)
	expire_transfer_attempts(timeout)
	if attempt.interaction_id:
		# The agent is routing this call again (the first transfer didn't happen) - free whoever it got before.
		for name in frappe.db.sql(
			f"select name from `tab{ATTEMPT_DOCTYPE}` where interaction_id = %(iid)s and status = %(routed)s for update",
			{"iid": attempt.interaction_id, "routed": ROUTED},
			pluck=True,
		):
			_close_attempt(name, NOT_CONNECTED, "Not connected: the agent routed this call again", now_datetime())
	busy = _busy_since(timeout)
	unavailable = {e.executive_name for e in executives if cint(e.on_break) or e.executive_name in busy}
	response["available"] = [e.executive_name for e in executives if e.executive_name not in unavailable]

	def why_unavailable(e):
		return "on break" if cint(e.on_break) else f"busy since {busy[e.executive_name]:%H:%M:%S}"

	def route(e, routed_by):
		name = _write_attempt(
			{**attempt, "status": ROUTED, "routed_by": routed_by, "executive": e.executive_name, "user": e.user, "target": _canonical(e.phone)},
			notes,
		)
		return {
			**response,
			"open": True,
			"target": _canonical(e.phone),
			"target_name": e.executive_name,
			"executive": e.executive_name,
			"routed_by": routed_by,
			"reason": None,
			"decision": "TRANSFER",
			"available": [n for n in response["available"] if n != e.executive_name],
			"attempt": name,
		}

	if requested:
		match = _match_executive(requested, executives)
		if not match:
			return refuse("executive_not_found", "no enabled executive by that name")
		if match.executive_name in unavailable:
			return refuse("executive_busy", f"{match.executive_name} is {why_unavailable(match)}")
		notes.append(f"matched {match.executive_name}")
		return route(match, "requested")

	if cint(settings.sticky_agent):
		sticky = _sticky_executive(ctx, executives, notes)
		if sticky and sticky.executive_name not in unavailable:
			return route(sticky, "sticky")
		if sticky:
			notes.append(f"{sticky.executive_name} is {why_unavailable(sticky)}, falling through to round robin")

	chosen = _round_robin(executives, unavailable, notes)
	if not chosen:
		return refuse("all_busy", "no enabled executive is free" if executives else "no enabled executive with a number")
	return route(chosen, "round_robin")


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def transfer_target(
	phone: str | None = None, key: str | None = None, executive: str | None = None, interaction_id: str | None = None
):
	"""
	Business Purpose: [BR-TEL-006] The single routing endpoint: whether a
	live call may be transferred to a person right now, and to whom.
	Hours, days, time zone, "callers on record only", the executives and
	their aliases, sticky routing and the busy timeout all come from Sarvam
	Voice Agent Settings.

	Order: the existing gates (hours/days, known caller); then the executive
	the caller named (`executive`, matched by name or alias); else, with
	Sticky Agent on, the executive who last took this caller's transferred
	call, else their lead / account owner; else round robin over the free
	executives. A busy or on-break sticky executive falls through to round
	robin; a busy named one is refused. Checking and routing hold a row lock
	on the executives, and the Routed row is written in the same
	transaction, so two callers can never get the same executive.

	Never blocks a call on an error: anything unexpected returns open false,
	reason "error" (and is logged), and the agent takes a callback.

	Args:
		phone (str): The caller's number, any spelling.
		key (str): Must match Sarvam Voice Agent Settings.webhook_secret.
		executive (str | None): The name the caller asked for.
		interaction_id (str | None): Sarvam's interaction id for this call -
			the call-end webhook closes the attempt by it.

	Returns:
		dict: {allowed, open, target (E.164), executive, routed_by
		(requested / sticky / round_robin), reason (when open is false:
		outside_hours, unknown_caller, executive_not_found, executive_busy,
		all_busy, error), available (names free right now), attempt,
		hours_text, decision (TRANSFER / CALLBACK), target_name (=
		executive), then / then_names (always empty - every transfer is
		routed here)}. A blocked/foreign caller gets only the gate's
		{allowed, reason, message}.
	"""
	_check_webhook_key(key)
	frappe.db.savepoint("voice_agent_transfer")
	try:
		gate = evaluate(phone)
		if not gate["allowed"]:
			return gate
		with _as_automation_user():
			return _route(phone, (executive or "").strip(), interaction_id)
	except Exception:
		frappe.db.rollback(save_point="voice_agent_transfer")
		frappe.log_error(title="Sarvam transfer_target failed")
		frappe.local.flags.commit = True  # keep the Error Log
		try:
			hours_text = _hours_text(_settings())
		except Exception:
			hours_text = ""
		return {
			"allowed": True, "open": False, "target": None, "target_name": None, "executive": None, "routed_by": None,
			"then": [], "then_names": [], "decision": "CALLBACK", "available": [], "attempt": None,
			"reason": "error", "hours_text": hours_text,
		}


def _close_transfer_attempts(call_log, interaction_id, variables):
	"""
	[BR-TEL-006] The call-end webhook's half of the busy ledger, matched only
	by interaction id (never by executive), and idempotent - only a Routed
	row ever changes, so a late or repeated delivery changes nothing.

	- `transferred` true: the newest Routed row becomes Connected and the
	  Call Log's receiver is that executive's user. The executive stays busy
	  until the busy timeout (then Ended) - this webhook arrives when the
	  agent hands over, not when the executive's call ends.
	- `transferred` false or missing: Not connected - the executive is free
	  at once.
	- No attempt for the interaction: nothing.
	"""
	if not interaction_id:
		return
	attempts = frappe.get_all(
		ATTEMPT_DOCTYPE,
		{"interaction_id": interaction_id, "status": ("!=", REFUSED)},
		["name", "status", "user"],
		order_by="creation desc",
	)
	if not attempts:
		return
	transferred = str(_first(variables, TRANSFERRED_KEYS) or "").strip().lower() in _TRUE
	latest = attempts[0]
	for row in attempts:
		if row.status != ROUTED:
			continue
		if transferred and row.name == latest.name:
			_close_attempt(row.name, CONNECTED, "Connected: call-end webhook says transferred; busy until the timeout")
		else:
			_close_attempt(row.name, NOT_CONNECTED, "Not connected: call-end webhook says not transferred", now_datetime())
	if transferred and latest.user:
		call_log.receiver = latest.user


@frappe.whitelist()
def busy_executives():
	"""
	[BR-TEL-006] Who can't take a transferred call right now and since when,
	for the Settings form's "Who Is Busy": every enabled executive with
	busy / on_break, the open attempt's status, caller and when it frees up.
	"""
	frappe.only_for((*MANAGER_ROLES, "Sales User"))
	timeout = _busy_timeout(_settings())
	open_rows = frappe.get_all(
		ATTEMPT_DOCTYPE,
		{"status": ("in", BUSY_STATUSES), "routed_at": (">=", _busy_cutoff(timeout))},
		["name", "executive", "status", "routed_at", "caller_phone"],
		order_by="routed_at asc",
	)
	by_executive = {}
	for row in open_rows:
		by_executive.setdefault(row.executive, row)
	result = []
	for e in _executive_rows():
		row = by_executive.get(e.executive_name)
		result.append(
			{
				"executive": e.executive_name,
				"on_break": cint(e.on_break),
				"busy": bool(row) or bool(cint(e.on_break)),
				"status": row.status if row else None,
				"since": row.routed_at if row else None,
				"free_at": add_to_date(row.routed_at, minutes=timeout) if row else None,
				"caller_phone": row.caller_phone if row else None,
				"attempt": row.name if row else None,
			}
		)
	return result


@frappe.whitelist(methods=["POST"])
def clear_busy_executives():
	"""
	[BR-TEL-006] Frees every executive the busy ledger holds now (Routed ->
	Expired, Connected -> Ended, noting who cleared them). On Break ticks
	are the executives' own and are left as they are.
	"""
	frappe.only_for(MANAGER_ROLES)
	note = f"cleared by {frappe.session.user}"
	rows = frappe.get_all(ATTEMPT_DOCTYPE, {"status": ("in", BUSY_STATUSES)}, ["name", "status"])
	for row in rows:
		new = EXPIRED if row.status == ROUTED else ENDED
		_close_attempt(row.name, new, f"{new}: {note}", now_datetime())
	return {"cleared": len(rows)}


# --------------------------------------------------------------------------
# 5b. Orderable items  [BR-CRM-006]
# --------------------------------------------------------------------------

_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|l|g|gm|kg)\b", re.IGNORECASE)


def _caller_group(ctx):
	"""(category, customer group) the caller is quoted under - the Customer's, else the Lead's category default."""
	if ctx.customer:
		return ctx.customer.category, ctx.customer.customer_group
	if ctx.lead:
		category = (ctx.lead.get("caller_category") or "").strip().lower() or None
		row = _category_default(category)
		return category, row.customer_group if row else None
	return None, None


def _orderable_item_rows(settings):
	packs = {r.item_code for r in settings.pack_items}
	rows = frappe.get_all(
		"Item",
		filters={
			"disabled": 0,
			"has_variants": 0,
			"is_sales_item": 1,
			"item_group": settings.orderable_item_group or DEFAULT_ORDERABLE_ITEM_GROUP,
		},
		fields=["name", "item_name", "stock_uom", "custom_voice_name"],
		order_by="item_name asc",
	)
	return [
		r for r in rows
		if r.name not in packs and NOT_ORDERABLE_TEXT not in f"{r.name} {r.item_name}".lower()
	]


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def orderable_items(phone: str | None = None, key: str | None = None):
	"""
	Business Purpose: [BR-CRM-006] The items a retailer, wholesale or
	distributor caller may order on the call - enabled, non-template sales
	Items of the Orderable Item Group, not a pack and not a sample. A caller
	whose customer group buys the packs (Pack Items in the settings - the
	individuals) or who is not on record gets an empty list: they order the
	packs. Read-only.

	Returns:
		dict: {allowed, category, customer_group, price_list, items:
		[{item_code, item_name, voice_name, size, uom, has_price}]}.
		`voice_name` is the Item's Voice Name (its item name when blank);
		`size` is read from the item name ("12.6 ML"); qty is in `uom`, the
		unit the price list is per; `has_price` is false when the caller's
		price list has no rate for it (upsert_quote would say
		PRICE_NOT_FOUND). A blocked/foreign caller gets only the gate's
		{allowed, reason, message}.
	"""
	_check_webhook_key(key)
	gate = evaluate(phone)
	if not gate["allowed"]:
		return gate
	settings = _settings()
	with _as_automation_user():
		ctx = _resolve(phone)
		category, group = _caller_group(ctx)
		empty = {"allowed": True, "category": category, "customer_group": group, "price_list": None, "items": []}
		if not group or group in {r.customer_group for r in settings.pack_items}:
			return empty
		party, _err = _quote_party(ctx)
		price_list = party.price_list if party else None
		items = []
		for r in _orderable_item_rows(settings):
			size = _SIZE.search(r.item_name or r.name)
			items.append(
				{
					"item_code": r.name,
					"item_name": r.item_name,
					"voice_name": (r.custom_voice_name or "").strip() or r.item_name,
					"size": f"{size.group(1)} {size.group(2).upper()}" if size else None,
					"uom": r.stock_uom,
					"has_price": bool(price_list and frappe.db.exists("Item Price", {"item_code": r.name, "price_list": price_list})),
				}
			)
		return {**empty, "price_list": price_list, "items": items}


# --------------------------------------------------------------------------
# 6. Call ended  [BR-TEL-007] - called from sarvam_telephony.handle_inbound_webhook
# --------------------------------------------------------------------------


TRANSCRIPT_NOTE_TITLE = "Call transcript"


def save_transcript_note(call_log, transcript):
	"""
	Business Purpose: [BR-TEL-007] Saves the call-ended webhook's
	`interaction_transcript` (Sarvam's turn list, `[{role, en_text}, ...]`) as
	an FCRM Note referencing the Call Log - the same form the agent's own
	"Call transcript: <date>" notes take - instead of a comment. A redelivered
	webhook updates the same Note rather than adding another.

	Args:
		call_log (Document): The CRM Call Log the webhook just saved.
		transcript (list | str | None): The payload's `interaction_transcript`.

	Returns:
		str | None: The FCRM Note's name, or None when there was no transcript.
	"""
	transcript = _parse_json_arg(transcript, None)
	if not transcript:
		return None
	if isinstance(transcript, list):
		lines = [f"{turn.get('role', '?')}: {turn.get('en_text') or turn.get('text') or ''}" for turn in transcript if isinstance(turn, dict)]
	else:
		lines = str(transcript).splitlines()
	content = "".join(f"<p>{frappe.utils.escape_html(line)}</p>" for line in lines if line.strip())
	if not content:
		return None

	existing = frappe.db.get_value(
		"FCRM Note",
		{"reference_doctype": "CRM Call Log", "reference_docname": call_log.name, "title": ("like", f"{TRANSCRIPT_NOTE_TITLE}:%")},
		"name",
	)
	if existing:
		frappe.db.set_value("FCRM Note", existing, "content", content)
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "FCRM Note",
				"title": f"{TRANSCRIPT_NOTE_TITLE}: {nowdate()}",
				"content": content,
				"reference_doctype": "CRM Call Log",
				"reference_docname": call_log.name,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def apply_call_outcome(call_log, payload):
	"""
	Business Purpose: [BR-TEL-007] The end-of-call write that replaces the
	agent's update_call_log / update_call_log_conversation_ref tools: stores
	the agent's output variables on the Call Log, the conversation ref, the
	call summary as an FCRM Note linked from the Call Log, and any
	`preferences` object onto the caller's Lead/Contact.

	For a blocked or foreign caller only the raw variables are kept on the
	Call Log - no Note or preference is written against their records.

	Args:
		call_log (Document): The CRM Call Log `handle_inbound_webhook` just saved.
		payload (dict): The call-ended webhook body.
	"""
	variables = _parse_json_arg(payload.get("output_agent_variables"), {}) or {}
	if not isinstance(variables, dict):
		variables = {}
	summary = _first(variables, SUMMARY_KEYS) or _first(payload, SUMMARY_KEYS)
	if not variables and not summary:
		return

	values = {"custom_agent_variables": json.dumps(variables)} if variables else {}
	ref = _first(variables, CONVERSATION_REF_KEYS) or _first(payload, CONVERSATION_REF_KEYS)
	if ref:
		values["custom_conversation_ref"] = str(ref)

	phone = call_log.get("from")
	if evaluate(phone)["allowed"]:
		if summary and not call_log.note:
			note = frappe.get_doc(
				{
					"doctype": "FCRM Note",
					"title": f"Call summary: {nowdate()}",
					"content": str(summary),
					# CRM Call Log defaults its reference type to CRM Lead even
					# with no record - only a real link is used, else the log itself.
					"reference_doctype": call_log.reference_doctype if call_log.reference_docname else "CRM Call Log",
					"reference_docname": call_log.reference_docname or call_log.name,
				}
			).insert(ignore_permissions=True)
			values["note"] = note.name

		preferences = variables.get(PREFERENCES_KEY)
		if isinstance(preferences, str):
			preferences = _parse_json_arg(preferences, None)
		if isinstance(preferences, dict) and preferences:
			ctx = _resolve(phone)
			target = ("CRM Lead", ctx.lead["name"]) if ctx.lead else (("Contact", ctx.contact["name"]) if ctx.contact else None)
			if target:
				current = _parse_json_arg(frappe.db.get_value(*target, "custom_caller_preferences"), {}) or {}
				frappe.db.set_value(*target, "custom_caller_preferences", json.dumps({**current, **preferences}))

	if values:
		call_log.db_set(values, update_modified=False)


# --------------------------------------------------------------------------
# 7. Call ended - the CRM Call Log itself  [BR-TEL-005]
# --------------------------------------------------------------------------

BLOCKED_CALL_STATUS = "Blocked"
REASON_ON_BLOCKED_LIST = "on blocked list"
REASON_NON_INDIAN = "non-Indian number"
REASON_TRANSFERRED = "transferred"
# Agent-defined output variable the agent sets when it transferred the call.
TRANSFERRED_KEYS = ("transferred", "call_transferred")
_TRUE = ("1", "true", "yes", "y")


def _payload_datetime(value):
	"""
	A payload time (ISO 8601 with or without an offset, or epoch seconds /
	milliseconds) as a naive datetime in the site's time zone, or None.
	"""
	if value in (None, ""):
		return None
	try:
		if isinstance(value, (int, float)) or str(value).strip().isdigit():
			stamp = float(value)
			moment = datetime.fromtimestamp(stamp / 1000 if stamp > 1e12 else stamp, tz=ZoneInfo("UTC"))
		else:
			from dateutil import parser

			moment = parser.parse(str(value))
	except (ValueError, OverflowError, TypeError):
		return None
	if moment.tzinfo:
		moment = moment.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
	return moment


def _call_number(raw):
	"""
	[BR-TEL-005] The caller's number for the Call Log, and whether it is
	foreign: an Indian mobile as +91 and ten digits; a SHA-256 hash looked up
	like caller_gate.check (unmatched -> blank, not foreign); anything else
	non-blank is foreign and kept as received (blank if it isn't even a
	valid phone number, so the Call Log still saves).

	Returns:
		tuple: (number for the log, foreign: bool, the raw value as sent).
	"""
	raw = "" if raw is None else str(raw).strip()
	if not raw:
		return "", False, raw
	if _PHONE_HASH.fullmatch(raw):
		return number_for_hash(raw) or "", False, raw
	mobile = _indian_mobile(raw)
	if mobile:
		return mobile, False, raw
	try:
		frappe.utils.validate_phone_number(raw, throw=True)
		return raw, True, raw
	except frappe.ValidationError:
		return "", True, raw


def _caller_never_spoke(payload, transcript):
	"""A zero-length call, or a transcript with no turn from the caller (they hung up at the greeting)."""
	duration = payload.get("duration")
	if duration not in (None, "") and flt(duration) <= 0:
		return True
	if isinstance(transcript, list):
		return not any(
			isinstance(turn, dict)
			and (turn.get("role") or "").lower() == "user"
			and (turn.get("en_text") or turn.get("text") or "").strip()
			for turn in transcript
		)
	return False


def _link_callback_tasks(call_log, since):
	"""
	[BR-TEL-005] Links the callback Tasks save_request made for this caller
	during the call to the Call Log (its Links table), so the team can go
	from the call to the callback.
	"""
	if call_log.reference_doctype not in ("CRM Lead", "CRM Deal") or not call_log.reference_docname:
		return
	filters = {
		"reference_doctype": call_log.reference_doctype,
		"reference_docname": call_log.reference_docname,
		"title": ("like", f"{CALLBACK_TASK_TITLE_PREFIX}%"),
		"creation": (">=", since),
	}
	automation_user = get_automation_user()
	if automation_user:
		filters["owner"] = automation_user
	linked = {(l.link_doctype, str(l.link_name)) for l in call_log.get("links") or []}
	for task in frappe.get_all("CRM Task", filters=filters, pluck="name", order_by="creation asc"):
		if ("CRM Task", str(task)) not in linked:
			call_log.append("links", {"link_doctype": "CRM Task", "link_name": str(task)})


def record_inbound_call(payload):
	"""
	Business Purpose: [BR-TEL-005] The CRM Call Log for one inbound
	voice-agent call, from Sarvam's call-ended payload - created, or updated
	when the same `interaction_id` arrives again (one log per interaction).

	- Type Incoming; from the caller's number (+91 and ten digits; a hash
	  is looked up as caller_gate.check does); to the number they called.
	- Linked to the caller's CRM Lead, else Contact, else Customer (the
	  voice agent's own lookup) - never creating one; a caller not on record
	  gets an unlinked log.
	- Status from the number, never from the call's length or end reason:
	  on the Blocked Contact list -> "Blocked" ("on blocked list", linked to
	  their Customer, else the Blocked Contact); a non-Indian number ->
	  "Blocked" ("non-Indian number", number kept as received). Otherwise
	  "No Answer" when the caller never spoke, else "Completed" (reason
	  "transferred" when the agent's `transferred` output variable says so).
	  A blank or unmatched number is not a block.
	- Start/end time and duration from the payload; the summary and
	  transcript as FCRM Notes on the log (apply_call_outcome /
	  save_transcript_note); this call's callback Tasks linked to it.
	- Closes this interaction's Sarvam Transfer Attempt ([BR-TEL-006],
	  _close_transfer_attempts) and sets the receiver when it was transferred.
	- Creates no Lead, Deal or Task.

	Args:
		payload (dict): The call-ended webhook body (key already stripped).

	Returns:
		Document: The saved CRM Call Log.
	"""
	interaction_id = _first(payload, CALL_ID_KEYS)
	if not interaction_id:
		raise frappe.ValidationError(f"Sarvam call-ended payload has no interaction id ({', '.join(CALL_ID_KEYS)})")

	number, foreign, raw = _call_number(_first(payload, CALLER_PHONE_KEYS))
	blocked = bool(number) and not foreign and is_blocked_number(number)
	transcript = payload.get("interaction_transcript")
	if isinstance(transcript, str):
		try:
			transcript = json.loads(transcript)
		except ValueError:
			pass
	variables = payload.get("output_agent_variables")
	if isinstance(variables, str):
		try:
			variables = json.loads(variables)
		except ValueError:
			variables = None
	variables = variables if isinstance(variables, dict) else {}

	if frappe.db.exists("CRM Call Log", interaction_id):
		call_log = frappe.get_doc("CRM Call Log", interaction_id)
	else:
		call_log = frappe.new_doc("CRM Call Log")
		call_log.id = interaction_id
		call_log.type = "Incoming"
		call_log.telephony_medium = "Sarvam"

	call_log.set("from", number)
	called = payload.get("agent_phone_number")
	if called:
		call_log.to = _canonical(called)

	ctx = _resolve(number) if number and not foreign else frappe._dict(lead=None, contact=None, customer=None)
	reason = None
	if blocked:
		status, reason = BLOCKED_CALL_STATUS, REASON_ON_BLOCKED_LIST
		reference = (
			("Customer", ctx.customer.name)
			if ctx.customer
			else ("Blocked Contact", frappe.db.get_value("Blocked Contact", {"mobile_no": last_10_digits(number), "enabled": 1}, "name"))
		)
	elif foreign:
		status, reason = BLOCKED_CALL_STATUS, REASON_NON_INDIAN if number else f"{REASON_NON_INDIAN}: {raw}"[:140]
		reference = (None, None)
	else:
		status = "No Answer" if _caller_never_spoke(payload, transcript) else "Completed"
		if status == "Completed" and str(_first(variables, TRANSFERRED_KEYS) or "").strip().lower() in _TRUE:
			reason = REASON_TRANSFERRED
		if ctx.lead:
			reference = ("CRM Lead", ctx.lead["name"])
		elif ctx.contact:
			reference = ("Contact", ctx.contact["name"])
		elif ctx.customer:
			reference = ("Customer", ctx.customer.name)
		else:
			# Keep a link the call-started webhook made, if any.
			reference = (call_log.reference_doctype, call_log.reference_docname)
	call_log.reference_doctype, call_log.reference_docname = reference if reference[1] else (None, None)
	call_log.status = status
	call_log.custom_status_reason = reason

	start, end = _payload_datetime(payload.get("start_datetime")), _payload_datetime(payload.get("end_datetime"))
	if start:
		call_log.start_time = start
	if end:
		call_log.end_time = end
	if payload.get("duration") not in (None, ""):
		call_log.duration = flt(payload.get("duration"))
	elif start and end:
		call_log.duration = max((end - start).total_seconds(), 0)
	if payload.get("recording_url"):
		call_log.recording_url = payload.get("recording_url")

	_link_callback_tasks(call_log, start or nowdate())
	_close_transfer_attempts(call_log, interaction_id, variables)
	call_log.save(ignore_permissions=True)
	if not call_log.reference_docname and call_log.reference_doctype:
		# Insert re-applies the field's "CRM Lead" default - an unlinked log has no type either.
		call_log.db_set("reference_doctype", None, update_modified=False)

	apply_call_outcome(call_log, payload)
	save_transcript_note(call_log, transcript)
	return call_log
