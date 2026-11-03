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
- transfer_target                [BR-TEL-006]  who to transfer a live call to, if anyone

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
from frappe.utils import cint, flt, get_time, nowdate

from core_customizations.core_customizations import quotation_gst
from core_customizations.core_customizations.caller_gate import (
	_check_webhook_key,
	_resolve_customer,
	evaluate,
	get_automation_user,
	last_10_digits,
)
from core_customizations.core_customizations.lead_duplicate_guard import DUPLICATE_LEAD_MESSAGE
from core_customizations.core_customizations.phone_normalise import normalise
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

CLOSED_DEAL_STATUSES = ("Won", "Lost")
OPEN_TASK_STATUSES = ("Backlog", "Todo", "In Progress")

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
	request = getattr(frappe, "request", None)
	key = (request.args.get("key") if request else None) or kwargs.get("key")
	_check_webhook_key(key)

	payload = _request_payload(kwargs)
	payload.pop("key", None)
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
	filters = {"status": ("not in", CLOSED_DEAL_STATUSES)}
	if ctx.lead:
		filters["lead"] = ctx.lead["name"]
		return frappe.db.get_value("CRM Deal", filters, "name", order_by="creation desc")
	last10 = last_10_digits(ctx.phone)
	rows = frappe.db.sql(
		f"""select name from `tabCRM Deal` where status not in %(closed)s and {_match_sql('mobile_no')}
		    order by creation desc limit 1""",
		{"last10": last10, "closed": CLOSED_DEAL_STATUSES},
		pluck=True,
	)
	return rows[0] if rows else None


def _get_or_create_deal(ctx):
	"""[BR-CRM-004] Reuses the caller's open CRM Deal; creates one only when none is open."""
	existing = _open_deal(ctx)
	if existing:
		return existing, False
	deal = {
		"doctype": "CRM Deal",
		"status": _settings().deal_status or "Qualification",
		"mobile_no": ctx.phone,
	}
	if ctx.lead:
		deal.update(lead=ctx.lead["name"], lead_name=ctx.lead.get("lead_name"))
	if ctx.customer and frappe.db.exists("CRM Organization", ctx.customer.customer_name):
		deal["organization"] = ctx.customer.customer_name
	elif ctx.customer:
		deal["lead_name"] = ctx.customer.customer_name
	doc = frappe.get_doc(deal).insert(ignore_permissions=True)
	return doc.name, True


def _quote_party(ctx):
	"""
	[BR-CRM-006] Who a voice-agent Quotation is addressed to, and at what
	price list. An existing Customer is quoted as the Customer at their own
	price list. A caller with only a CRM Lead is quoted through a CRM Deal
	(ERPNext Quotations accept `CRM Deal`, never `CRM Lead`) at the price list
	their caller category maps to - a category with no price list is never
	quoted by the agent.
	"""
	if ctx.customer:
		price_list = (
			ctx.customer.default_price_list
			or frappe.db.get_value("Customer Group", ctx.customer.customer_group, "default_price_list")
			or frappe.db.get_single_value("Selling Settings", "selling_price_list")
		)
		return frappe._dict(
			quotation_to="Customer",
			party_name=ctx.customer.name,
			customer_group=ctx.customer.customer_group,
			price_list=price_list,
		), None

	if ctx.lead:
		row = _category_default(ctx.lead.get("caller_category"))
		if not row or not row.price_list:
			return None, _error(
				"QUOTE_NOT_AVAILABLE",
				"The team will call back with prices for this caller category.",
				caller_category=ctx.lead.get("caller_category"),
			)
		return frappe._dict(
			quotation_to="CRM Deal", party_name=None, customer_group=row.customer_group, price_list=row.price_list
		), None

	return None, _error("NOT_ON_RECORD", "Save the caller's name and number (save_request) before quoting.")


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

	return _quote_response(doc, not existing, deal)


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def upsert_quote(
	phone: str | None = None,
	key: str | None = None,
	items: str | list | None = None,
	ship_to_pincode: str | None = None,
	address_name: str | None = None,
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

	Returns:
		dict: {allowed, status: "quoted", quotation, created, deal, items,
		net_total, taxes: [{type, rate, amount}], shipping,
		rounding_adjustment, grand_total, rounded_total, total_to_say}, or
		{allowed, status: "error", error: <CODE>, message}.
	"""
	_check_webhook_key(key)
	gate = evaluate(phone)
	if not gate["allowed"]:
		return gate
	parsed, problem = _parse_items(items)
	if problem or not parsed:
		return _error("INVALID_ITEMS", problem or "items is empty")
	with _as_automation_user():
		return _upsert_quote(_resolve(phone), parsed, ship_to_pincode, address_name)


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
	"""[BR-CRM-004] One open callback task per record per day - a repeat save updates it."""
	settings = _settings()
	existing = frappe.db.get_value(
		"CRM Task",
		{
			"reference_doctype": reference_doctype,
			"reference_docname": reference_name,
			"status": ("in", OPEN_TASK_STATUSES),
			"owner": frappe.session.user,
			"creation": (">=", nowdate()),
		},
		"name",
	)
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


def _save_lead_address(lead, title, line, city, state, pincode):
	"""
	[BR-CRM-008] A new caller has no Customer, so their delivery address is
	saved as a real Shipping `Address` linked to their CRM Lead through its
	`links` Dynamic Link table - the same mechanism `contact_lead_link` uses
	to link a Lead's Contact. A repeat of the same line + pincode reuses the
	existing Address.

	Returns:
		tuple: (address name, None) or (None, warning) when a field Frappe's
		Address requires is missing - the request is still saved then, with
		the address kept only as text.
	"""
	state = state or (quotation_gst.state_from_pincode(pincode) if pincode else None)
	missing = [field for field, value in (("city", city), ("pincode", pincode), ("state", state)) if not value]
	if missing:
		return None, f"ADDRESS_NOT_SAVED: missing {', '.join(missing)}"

	for existing in _linked_addresses(("CRM Lead", lead)):
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
				"is_shipping_address": 1,
				"links": [{"link_doctype": "CRM Lead", "link_name": lead}],
			}
		).insert(ignore_permissions=True)
	except frappe.ValidationError as e:
		if "CALLER_BLOCKED:" in str(e):
			raise
		raise _RequestRefused(
			_error("ADDRESS_INVALID", "That address could not be saved - check the city, state and pincode.", detail=str(e))
		) from e
	return doc.name, None


def _save_request(
	ctx, *, name, caller_type, organization, items, address, whatsapp_number, notes, store_type, area,
	ship_to_pincode, address_name, city, state, pincode,
):
	result = {
		"allowed": True, "status": "saved", "lead": None, "deal": None, "quotation": None, "task": None,
		"quote": None, "warnings": [], "message": "", "address": None,
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
	if category and not _category_rows(category):
		result["warnings"].append(f"UNKNOWN_CATEGORY: {caller_type}")
	elif category and not _category_default(category):
		result["warnings"].append(f"CUSTOMER_GROUP_NEEDS_REVIEW: {category}")

	description = _description_lines(caller_type, store_type, area, notes, address, whatsapp_number, pincode)
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

	# [BR-CRM-008] A lead (no Customer) giving a new address gets a real, linked Address.
	if not saved_address and (address or "").strip() and ctx.lead and not ctx.customer:
		new_address, warning = _save_lead_address(ctx.lead["name"], display_name or ctx.phone, address, city, state, pincode)
		if warning:
			result["warnings"].append(warning)
		else:
			result["address"] = new_address

	quoted = False
	if items:
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
		else:
			ref = ("CRM Deal", result["deal"] or _get_or_create_deal(ctx)[0])
			result["deal"] = ref[1]
		flags = "\n".join(result["warnings"])
		task_description = "\n".join(filter(None, [f"Phone: {ctx.phone}", description, flags]))
		result["task"] = _upsert_callback_task(*ref, f"Callback: {display_name or ctx.phone}", task_description)

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

	All-or-nothing: if any write fails, nothing is kept.

	Returns:
		dict: {allowed, status: "saved" | "duplicate" | "blocked" | "error",
		lead, deal, quotation, task, quote, warnings, message, address}.
	"""
	_check_webhook_key(key)
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


def _transfer_window_open(settings):
	tz = ZoneInfo(settings.transfer_timezone or "Asia/Kolkata")
	now = _now(tz)
	days = [d.strip()[:3].title() for d in (settings.transfer_days or "").split(",") if d.strip()]
	if now.strftime("%a") not in days:
		return False, now
	start = get_time(settings.transfer_start_time or "00:00:00")
	end = get_time(settings.transfer_end_time or "23:59:59")
	return start <= now.time().replace(microsecond=0) < end, now


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def transfer_target(phone: str | None = None, key: str | None = None):
	"""
	Business Purpose: [BR-TEL-006] Whether a live call may be transferred to
	a person right now, and to whom - replaces check_transfer_hours
	(timeapi.io) and the route_to_* tools (httpbin). Executives (in order),
	hours, days, time zone and the "callers on record only" rule all come
	from Sarvam Voice Agent Settings.

	Returns:
		dict: {allowed, open, target, target_name, then: [...], reason,
		decision}. When `open` is false, `decision` is "CALLBACK" and
		`reason` is OUTSIDE_HOURS / NOT_ON_RECORD / NO_EXECUTIVES.
	"""
	_check_webhook_key(key)
	gate = evaluate(phone)
	if not gate["allowed"]:
		return gate

	settings = _settings()
	closed = {"allowed": True, "open": False, "target": None, "target_name": None, "then": [], "decision": "CALLBACK"}

	is_open, now = _transfer_window_open(settings)
	if not is_open:
		return {**closed, "reason": "OUTSIDE_HOURS", "checked_at": now.isoformat(timespec="minutes")}

	if cint(settings.transfer_known_callers_only):
		with _as_automation_user():
			ctx = _resolve(phone)
		if not (ctx.lead or ctx.contact or ctx.customer):
			return {**closed, "reason": "NOT_ON_RECORD"}

	executives = [e for e in settings.transfer_executives if e.enabled and e.phone]
	if not executives:
		return {**closed, "reason": "NO_EXECUTIVES"}

	return {
		"allowed": True,
		"open": True,
		"target": _canonical(executives[0].phone),
		"target_name": executives[0].executive_name,
		"then": [_canonical(e.phone) for e in executives[1:]],
		"then_names": [e.executive_name for e in executives[1:]],
		"reason": None,
		"decision": "TRANSFER",
	}


# --------------------------------------------------------------------------
# 6. Call ended  [BR-TEL-007] - called from sarvam_telephony.handle_inbound_webhook
# --------------------------------------------------------------------------


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
	if not isinstance(variables, dict) or not variables:
		return

	values = {"custom_agent_variables": json.dumps(variables)}
	ref = _first(variables, CONVERSATION_REF_KEYS) or _first(payload, CONVERSATION_REF_KEYS)
	if ref:
		values["custom_conversation_ref"] = str(ref)

	phone = call_log.get("from")
	if evaluate(phone)["allowed"]:
		summary = _first(variables, SUMMARY_KEYS)
		if summary and not call_log.note:
			note = frappe.get_doc(
				{
					"doctype": "FCRM Note",
					"title": f"Call summary: {nowdate()}",
					"content": str(summary),
					"reference_doctype": call_log.reference_doctype or "CRM Call Log",
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

	call_log.db_set(values, update_modified=False)
