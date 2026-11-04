# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
[BR-CRM-006] Seeds what orderable_items needs on an existing site:

- Orderable Item Group on Sarvam Voice Agent Settings - an existing Single
  does not pick up a new field's default, it reads blank.
- The Voice Name of the two items retailers order, when the item exists and
  has none yet (staff edits are never overwritten).
"""

import frappe

SETTINGS = "Sarvam Voice Agent Settings"
ORDERABLE_ITEM_GROUP = "Products"
VOICE_NAMES = {"SASB-12.6 ML": "big bottle", "SASB-1.4 ML": "small pack"}


def execute():
	frappe.reload_doc("core_customizations", "doctype", "sarvam_voice_agent_settings")

	if not frappe.db.get_single_value(SETTINGS, "orderable_item_group") and frappe.db.exists("Item Group", ORDERABLE_ITEM_GROUP):
		frappe.db.set_single_value(SETTINGS, "orderable_item_group", ORDERABLE_ITEM_GROUP)

	if not frappe.get_meta("Item").has_field("custom_voice_name"):
		# Post-model-sync patches run before migrate syncs fixtures - bring the
		# Item Voice Name custom field in now so it can be filled.
		from frappe.utils.fixtures import sync_fixtures

		sync_fixtures("core_customizations")
		frappe.clear_cache(doctype="Item")
	if frappe.get_meta("Item").has_field("custom_voice_name"):
		for item_code, voice_name in VOICE_NAMES.items():
			if frappe.db.exists("Item", item_code) and not frappe.db.get_value("Item", item_code, "custom_voice_name"):
				frappe.db.set_value("Item", item_code, "custom_voice_name", voice_name, update_modified=False)
