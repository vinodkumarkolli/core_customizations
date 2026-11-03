# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Seeds the business values the voice agent's server-side methods read from
Sarvam Voice Agent Settings ([BR-TEL-006], [BR-CRM-005], [BR-CRM-006]) with
the values the agent's prompt hardcoded until now. Only fills a table that is
still empty, and skips any row whose linked record doesn't exist on this site,
so re-running it (or running it on a site configured by hand) changes nothing.
"""

import frappe

SETTINGS = "Sarvam Voice Agent Settings"

TRANSFER_EXECUTIVES = [
	("Kalpana", "+918248207671", "kkalpanamuthu10@gmail.com"),
	("Sravya", "+918106557040", None),
	("Vinod", "+918122586261", "vinodkumarkolli@gmail.com"),
]

# (category, customer_group, price_list, is_default)
CALLER_CATEGORIES = [
	("individual", "Individual", "Standard Selling", 1),
	("wholesale", "Commercial", None, 1),
	("distributor", "Commercial", None, 1),
	("retailer", "Chennai GT", None, 0),
	("retailer", "Chennai Pharma", None, 0),
	("retailer", "Coimbatore Customers", None, 0),
	("retailer", "MT Category D", None, 0),
	("retailer", "Pondichery Customers", None, 0),
]

PACK_ITEMS = [
	("SASB-50INR-PACK-4", "Individual", "Next Day Shipping"),
	("SASB-50INR-PACK-10", "Individual", "Next Day Shipping"),
	("SASB-50INR-PACK-20", "Individual", "Next Day Shipping"),
]


def execute():
	frappe.reload_doc("core_customizations", "doctype", "sarvam_transfer_executive")
	frappe.reload_doc("core_customizations", "doctype", "sarvam_caller_category")
	frappe.reload_doc("core_customizations", "doctype", "sarvam_pack_item")
	frappe.reload_doc("core_customizations", "doctype", "sarvam_voice_agent_settings")

	settings = frappe.get_single(SETTINGS)
	# A Check field's default isn't applied to an existing Single - it reads 0
	# until a value is stored, so "unset" has to be detected on tabSingles.
	known_flag_stored = frappe.db.sql(
		"select 1 from `tabSingles` where doctype = %s and field = 'transfer_known_callers_only'", SETTINGS
	)

	if not settings.transfer_executives:
		for name, phone, user in TRANSFER_EXECUTIVES:
			settings.append(
				"transfer_executives",
				{
					"executive_name": name,
					"phone": phone,
					"user": user if user and frappe.db.exists("User", user) else None,
					"enabled": 1,
				},
			)

	if not settings.caller_categories:
		for category, group, price_list, is_default in CALLER_CATEGORIES:
			if not frappe.db.exists("Customer Group", group):
				continue
			settings.append(
				"caller_categories",
				{
					"category": category,
					"customer_group": group,
					"price_list": price_list if price_list and frappe.db.exists("Price List", price_list) else None,
					"is_default": is_default,
				},
			)

	if not settings.pack_items:
		for item_code, group, rule in PACK_ITEMS:
			if all(
				(
					frappe.db.exists("Item", item_code),
					frappe.db.exists("Customer Group", group),
					frappe.db.exists("Shipping Rule", rule),
				)
			):
				settings.append("pack_items", {"item_code": item_code, "customer_group": group, "shipping_rule": rule})

	for field, value in (
		("transfer_start_time", "10:00:00"),
		("transfer_end_time", "20:00:00"),
		("transfer_days", "Mon,Tue,Wed,Thu,Fri,Sat"),
		("transfer_timezone", "Asia/Kolkata"),
		("callback_task_priority", "High"),
		("deal_status", "Qualification"),
	):
		if not settings.get(field):
			settings.set(field, value)
	if not known_flag_stored:
		settings.transfer_known_callers_only = 1

	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
