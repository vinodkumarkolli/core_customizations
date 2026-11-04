# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
[BR-CRM-011] The Customer behind a CRM Deal quotation is made when the
Quotation is submitted, so "Make Sales Order" always has one.

A new caller's quote is addressed to their CRM Deal (ERPNext Quotations never
take a CRM Lead). ERPNext only turns Lead / Prospect quotations into a
Customer; for a CRM Deal it just looks for a Customer whose `crm_deal` is that
Deal. The Frappe CRM integration would create one, but with no customer group
or price list (both mandatory here - so it fails) and by reusing any Customer
with the same name (so a new "Ravi Kumar" could take an existing Ravi Kumar's
order). This module does it instead, on Quotation `before_submit`:

- The caller's own Customer when there is one: the Deal's "Customer in
  ERPNext", else a Customer already on the caller's number.
- Otherwise a new Customer: name from the Deal's organisation / Lead; group
  from the Lead's caller category (Sarvam Voice Agent Settings > Caller
  Categories); price list = the list the Quotation was priced from; the
  caller's Contact linked (or created from the number); `crm_deal` set, so the
  Lead's saved Addresses follow it (lead_address_link) and ERPNext finds it
  for the Sales Order. A name another Customer already has gets the caller's
  last four digits ("Ravi Kumar - 6261").
- Nothing can be decided (no caller category with a default group) - the
  submit is refused with what to do, rather than failing later at the
  Sales Order.

`fill_sales_order_customer` (Sales Order `before_validate`) covers the one
case ERPNext's lookup misses: a reused Customer whose `crm_deal` points at an
older Deal.
"""

import frappe
from frappe import _

from core_customizations.core_customizations.caller_gate import last_10_digits

DEAL = "CRM Deal"


def _has_field(doctype, fieldname):
	return frappe.get_meta(doctype).has_field(fieldname)


def _deal_customer(deal):
	"""The Customer already recorded for this Deal, if any."""
	if _has_field("Customer", "crm_deal"):
		customer = frappe.db.get_value("Customer", {"crm_deal": deal.name})
		if customer:
			return customer
	recorded = deal.get("erpnext_customer")
	if recorded and frappe.db.exists("Customer", recorded):
		return recorded
	return None


def _deal_phone(deal, lead):
	return deal.get("mobile_no") or (lead.mobile_no if lead else None)


def _callers_customer(phone):
	"""A Customer already on the caller's number (the voice agent's own lookup)."""
	from core_customizations.core_customizations.voice_agent import _resolve

	if not last_10_digits(phone):
		return None, None
	ctx = _resolve(phone)
	return (ctx.customer.name if ctx.customer else None), ctx.contact


def _unique_customer_name(base, phone):
	"""`base`, or "base - <last 4 digits>" (then all 10) when another Customer has that name."""
	digits = last_10_digits(phone) or ""
	for candidate in (base, f"{base} - {digits[-4:]}" if digits else None, f"{base} - {digits}" if digits else None):
		if candidate and not frappe.db.exists("Customer", {"customer_name": candidate}):
			return candidate
	return f"{base} - {digits}" if digits else base


def _customer_group(lead):
	from core_customizations.core_customizations.voice_agent import _category_default

	category = (lead.get("custom_caller_category") or "").strip().lower() if lead else ""
	row = _category_default(category) if category else None
	return category, (row.customer_group if row else None)


def _link_contact(contact_name, customer):
	contact = frappe.get_doc("Contact", contact_name)
	if not any(l.link_doctype == "Customer" and l.link_name == customer for l in contact.links):
		contact.append("links", {"link_doctype": "Customer", "link_name": customer})
		contact.save(ignore_permissions=True)


def _record_on_deal(deal, customer):
	if _has_field(DEAL, "erpnext_customer") and deal.get("erpnext_customer") != customer:
		frappe.db.set_value(DEAL, deal.name, "erpnext_customer", customer, update_modified=False)


def _create_customer(quotation, deal, lead, phone, contact):
	category, group = _customer_group(lead)
	if not group:
		frappe.throw(
			_(
				"Can't make the Customer for {0}: {1}. Set the Lead's caller category to one with a default "
				"Customer Group in Sarvam Voice Agent Settings, or create the Customer and enter it as the "
				"Deal's \"Customer in ERPNext\" - then submit again."
			).format(
				deal.name,
				_("caller category \"{0}\" has no default Customer Group").format(category)
				if category
				else _("the Deal has no Lead with a caller category"),
			),
			title=_("Customer needed for the Sales Order"),
		)
	base = deal.get("organization") or (lead.lead_name if lead else None) or deal.get("lead_name")
	if not base:
		frappe.throw(_("Can't make the Customer for {0}: it has no organisation or lead name.").format(deal.name))

	customer = frappe.new_doc("Customer")
	customer.update(
		{
			"customer_name": _unique_customer_name(base.strip(), phone),
			"customer_type": "Company" if deal.get("organization") else "Individual",
			"customer_group": group,
			"default_price_list": quotation.selling_price_list,
			"gst_category": "Unregistered",
			"territory": deal.get("territory") if deal.get("territory") and frappe.db.exists("Territory", deal.territory) else None,
			"crm_deal": deal.name,
		}
	)
	if contact:
		customer.customer_primary_contact = contact
	elif phone:
		customer.mobile_no = phone  # ERPNext makes the primary Contact from it
	customer.insert(ignore_permissions=True)
	if contact:
		_link_contact(contact, customer.name)
	return customer.name


def ensure_customer(doc, method=None):
	"""
	Business Purpose: [BR-CRM-011] Quotation `before_submit` - makes sure a
	CRM Deal quotation has its Customer before it is submitted (see module
	docstring). Customer and Lead quotations are untouched.
	"""
	if doc.quotation_to != DEAL or not doc.party_name:
		return
	if not _has_field("Customer", "crm_deal"):
		frappe.throw(
			_("A CRM Deal quotation can only become a Sales Order with the ERPNext CRM integration on (ERPNext CRM Settings > Enabled)."),
			title=_("Customer needed for the Sales Order"),
		)
	if doc.meta.has_field("crm_deal") and not doc.get("crm_deal"):
		doc.crm_deal = doc.party_name  # quotations made before the integration was on

	deal = frappe.get_doc(DEAL, doc.party_name)
	customer = _deal_customer(deal)
	lead = (
		frappe.db.get_value("CRM Lead", deal.lead, ["name", "lead_name", "mobile_no", "custom_caller_category"], as_dict=True)
		if deal.get("lead")
		else None
	)
	phone = _deal_phone(deal, lead)
	contact = None
	if not customer:
		customer, found_contact = _callers_customer(phone)
		contact = found_contact.name if found_contact else None
	if customer:
		if not frappe.db.get_value("Customer", customer, "crm_deal"):
			frappe.db.set_value("Customer", customer, "crm_deal", deal.name, update_modified=False)
			# Link the Lead's saved addresses, as a save of the Customer would.
			from core_customizations.core_customizations.lead_address_link import on_customer_update

			on_customer_update(frappe.get_doc("Customer", customer))
	else:
		customer = _create_customer(doc, deal, lead, phone, contact)
	_record_on_deal(deal, customer)
	if doc.shipping_address_name:
		_link_address(doc.shipping_address_name, customer)


def _link_address(address_name, customer):
	"""The quote's delivery address must belong to the Customer, or the Sales Order refuses it."""
	exists = frappe.db.exists(
		"Dynamic Link", {"parenttype": "Address", "parent": address_name, "link_doctype": "Customer", "link_name": customer}
	)
	if not exists:
		address = frappe.get_doc("Address", address_name)
		address.append("links", {"link_doctype": "Customer", "link_name": customer})
		address.save(ignore_permissions=True)


def fill_sales_order_customer(doc, method=None):
	"""
	Business Purpose: [BR-CRM-011] Sales Order `before_validate` - a Sales
	Order made from a CRM Deal quotation whose Customer ERPNext didn't find
	(a reused Customer recorded on the Deal, not by `crm_deal`) gets that
	Customer.
	"""
	if doc.customer:
		return
	for item in doc.items:
		if item.get("prevdoc_docname"):
			to, deal = frappe.db.get_value("Quotation", item.prevdoc_docname, ["quotation_to", "party_name"]) or (None, None)
			if to == DEAL and deal:
				customer = _deal_customer(frappe.get_doc(DEAL, deal))
				if customer:
					doc.customer = customer
					doc.customer_name = frappe.db.get_value("Customer", customer, "customer_name")
					return
