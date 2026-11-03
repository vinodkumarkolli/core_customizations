# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""[BR-CRM-008] Seeds how many saved Addresses caller_context returns. An Int
field's default isn't applied to an existing Single, so it reads 0 until set."""

import frappe

SETTINGS = "Sarvam Voice Agent Settings"


def execute():
	frappe.reload_doc("core_customizations", "doctype", "sarvam_voice_agent_settings")
	stored = frappe.db.sql(
		"select 1 from `tabSingles` where doctype = %s and field = 'address_list_limit'", SETTINGS
	)
	if not stored:
		frappe.db.set_single_value(SETTINGS, "address_list_limit", 5)
