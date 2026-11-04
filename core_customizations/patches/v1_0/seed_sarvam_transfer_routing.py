# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
[BR-TEL-006] Seeds what the routing release needs on an existing site: Busy
Timeout on Sarvam Voice Agent Settings - an existing Single does not pick up
a new field's default, it reads blank.
"""

import frappe

SETTINGS = "Sarvam Voice Agent Settings"
BUSY_TIMEOUT_MINUTES = 5


def execute():
	frappe.reload_doc("core_customizations", "doctype", "sarvam_transfer_executive")
	frappe.reload_doc("core_customizations", "doctype", "sarvam_voice_agent_settings")
	frappe.reload_doc("core_customizations", "doctype", "sarvam_transfer_attempt")

	if not frappe.db.get_single_value(SETTINGS, "busy_timeout_minutes"):
		frappe.db.set_single_value(SETTINGS, "busy_timeout_minutes", BUSY_TIMEOUT_MINUTES)
