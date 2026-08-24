# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""
	Clean up obsolete Mobile App DocTypes, Module Def, and Social Login Key customizations.
	Runs in [pre_model_sync] before frappe.model.sync.sync_all() so that database records
	referencing 'Mobile App' do not trigger ModuleNotFoundError during schema migration.
	"""
	mobile_doctypes = [
		"Project Task Module Mapping",
		"Mobile App Module Submodule Configuration",
		"Mobile App Module Def",
		"Mobile App Submodule Def",
	]

	for dt in mobile_doctypes:
		if frappe.db.exists("DocType", dt):
			try:
				frappe.db.delete(dt)
			except Exception:
				pass
			try:
				frappe.delete_doc("DocType", dt, force=1, ignore_permissions=True)
			except Exception:
				pass

	# Remove Module Def 'Mobile App'
	if frappe.db.exists("Module Def", "Mobile App"):
		try:
			frappe.delete_doc("Module Def", "Mobile App", force=1, ignore_permissions=True)
		except Exception:
			pass

	# Clean up Social Login Key custom field and client script
	if frappe.db.exists("Custom Field", "Social Login Key-custom_default_login"):
		try:
			frappe.delete_doc("Custom Field", "Social Login Key-custom_default_login", force=1, ignore_permissions=True)
		except Exception:
			pass

	cs = frappe.db.get_value("Client Script", {"dt": "Social Login Key"}, "name")
	if cs:
		try:
			frappe.delete_doc("Client Script", cs, force=1, ignore_permissions=True)
		except Exception:
			pass

	frappe.db.commit()
