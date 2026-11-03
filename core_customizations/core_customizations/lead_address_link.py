# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
[BR-CRM-008] When a CRM Lead becomes a Customer, the Addresses saved against
the Lead (by the voice agent's save_request) are linked to the Customer too,
keeping the Lead link - so a returning caller is offered the same saved
address whichever record they now resolve to.

Neither conversion path carries a Lead's Addresses across by itself:
- CRM Lead -> CRM Deal (`crm_lead.convert_to_deal`) creates a Contact and a
  CRM Organization only.
- CRM Deal -> Customer (ERPNext CRM Settings' `create_customer_from_deal`,
  when that integration is enabled) links the Deal's Contacts and copies only
  the CRM Organization's address.
- A Customer created by hand in Desk has no link back to the Lead at all.

So the Lead is found from the Customer itself: its `crm_deal` (when the
integration's field exists) -> that Deal's Lead; else a Contact linked to
both the Customer and a CRM Lead; else the CRM Lead whose mobile number
matches the Customer's. Only exactly one Lead is ever used - when a step
finds several, that is logged to Error Log and nothing is linked.
"""

import frappe

from core_customizations.core_customizations.caller_gate import last_10_digits


def _addresses_of(link_doctype, link_name):
	return frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": link_doctype, "link_name": link_name},
		pluck="parent",
	)


def _log_undecided(customer_name, reason, candidates):
	"""
	[BR-CRM-008] Records that a Customer's Lead could not be decided, so
	nothing is linked silently wrong - and the team can see which Customers
	need their Lead addresses linked by hand. Logged once per Customer and
	reason (an ambiguous Customer would otherwise log on every save).
	"""
	title = f"Lead Address Link: could not decide the CRM Lead for Customer {customer_name}"[:140]
	# Error Log lives in Frappe's separate log database: frappe.db.exists would
	# look in the main database and never find it, so ask through the doctype API.
	if frappe.get_all("Error Log", filters={"method": title}, limit=1, pluck="name"):
		return
	frappe.log_error(
		title=title,
		message=f"{reason}. Candidate CRM Leads: {', '.join(sorted(candidates))}. "
		"No Lead Addresses were linked to this Customer; link the right Lead's Address by hand if needed.",
	)


def _leads_for_customer(customer):
	"""
	The one CRM Lead this Customer came from, as a set of 0 or 1 names.

	Tried in order, stopping at the first that decides: the Customer's
	`crm_deal` (definitive); a Contact linked to both the Customer and a CRM
	Lead; the CRM Lead on the Customer's mobile number. A step that finds
	more than one Lead is logged via `_log_undecided` and nothing is linked.
	"""
	crm_deal = customer.get("crm_deal") if customer.meta.has_field("crm_deal") else None
	if crm_deal:
		lead = frappe.db.get_value("CRM Deal", crm_deal, "lead")
		if lead:
			return {lead}

	contacts = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": customer.name},
		pluck="parent",
	)
	if contacts:
		via_contacts = set(
			frappe.get_all(
				"Dynamic Link",
				filters={"parenttype": "Contact", "parent": ("in", contacts), "link_doctype": "CRM Lead"},
				pluck="link_name",
			)
		)
		if len(via_contacts) == 1:
			return via_contacts
		if len(via_contacts) > 1:
			_log_undecided(customer.name, "The Customer's Contacts are linked to more than one CRM Lead", via_contacts)
			return set()

	last10 = last_10_digits(customer.get("mobile_no"))
	if last10:
		matches = set(
			frappe.db.sql(
				"""select name from `tabCRM Lead`
				   where right(regexp_replace(ifnull(mobile_no, ''), '[^0-9]', ''), 10) = %s""",
				last10,
				pluck=True,
			)
		)
		if len(matches) == 1:
			return matches
		if len(matches) > 1:
			_log_undecided(customer.name, f"More than one CRM Lead has the Customer's mobile number {customer.mobile_no}", matches)
	return set()


def link_lead_addresses(customer_name, leads):
	"""Adds a Customer link to every Address of `leads` that lacks one. Never removes a link."""
	already = set(_addresses_of("Customer", customer_name))
	for lead in leads:
		for address_name in _addresses_of("CRM Lead", lead):
			if address_name in already:
				continue
			try:
				address = frappe.get_doc("Address", address_name)
				address.append("links", {"link_doctype": "Customer", "link_name": customer_name})
				address.save(ignore_permissions=True)
				already.add(address_name)
			except Exception:
				# Never block the Customer/Contact save that triggered this.
				frappe.log_error(
					title=f"Could not link Address {address_name} of CRM Lead {lead} to Customer {customer_name}"
				)


def on_customer_update(doc, method=None):
	"""Customer `on_update` - covers Desk-created Customers and the CRM integration's `crm_deal`."""
	leads = _leads_for_customer(doc)
	if leads:
		link_lead_addresses(doc.name, leads)


def on_contact_update(doc, method=None):
	"""
	Contact `on_update` - the CRM integration links Contacts to a new Customer
	only after inserting it, so the Customer's own hook can't see them yet.
	"""
	links = doc.get("links") or []
	customers = {l.link_name for l in links if l.link_doctype == "Customer"}
	leads = {l.link_name for l in links if l.link_doctype == "CRM Lead"}
	if not customers or not leads:
		return
	if len(leads) > 1:
		for customer in customers:
			_log_undecided(customer, f"Contact {doc.name} is linked to more than one CRM Lead", leads)
		return
	for customer in customers:
		link_lead_addresses(customer, leads)
