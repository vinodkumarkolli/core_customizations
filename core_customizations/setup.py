# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt
"""
Setup module for core_customizations app.

This module runs after migration to configure roles and permissions.
"""

import frappe


def after_migrate():
	roles_permissions = {
		"Employee Self Service": [
			{"parent": "Workflow State", "read": 1, "write": 0, "create": 0, "delete": 0},
			{"parent": "Workflow", "read": 1, "write": 0, "create": 0, "delete": 0},
			{"parent": "Workflow Action Master", "read": 1, "write": 0, "create": 0, "delete": 0},
			{"parent": "Project", "read": 1, "write": 0, "create": 0, "delete": 0},
			{"parent": "Mode of Payment", "read": 1, "write": 0, "create": 0, "delete": 0},
			{"parent": "Employee", "read": 1, "write": 0, "permlevel": 1},
			{"parent": "Supplier", "read": 1, "write": 0, "create": 0, "delete": 0,"permlevel": 0},
			{"parent":"Item Price","read": 1, "write": 0, "create": 0, "delete": 0},
			{"parent":"Item Tax Template","read": 1, "write": 0, "create": 0, "delete": 0}
		],
		"System Manager": [
			{"parent": "Employee", "read": 1, "write": 1, "permlevel": 1},
		]
	}

	for role_name, permissions in roles_permissions.items():
		if not frappe.db.exists("Role", role_name):
			print(f"Role {role_name} not found.")
			continue

		updated_doctypes = []  # Initialize list for each role

		for p in permissions:
			doctype = p["parent"]

			# Fix: Ensure standard permissions are copied to Custom DocPerms
			# Frappe ignores standard DocPerms if ANY Custom DocPerm exists for the DocType.
			# So we must ensure all standard permissions are migrated to Custom DocPerms.
			standard_perms = frappe.get_all("DocPerm", filters={"parent": doctype}, fields="*")
			for perm in standard_perms:
				if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": perm.role, "permlevel": perm.permlevel, "if_owner": perm.if_owner}):
					d = frappe.new_doc("Custom DocPerm")
					perm.pop("name", None)
					perm.pop("creation", None)
					perm.pop("modified", None)
					perm.pop("owner", None)
					perm.pop("docstatus", None)
					perm.pop("idx", None)
					d.update(perm)
					d.insert()

			try:
				# Check if permission already exists for this role
				permlevel = p.get("permlevel", 0)
				doc_name = frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role_name, "permlevel": permlevel})
				if doc_name:
					d = frappe.get_doc("Custom DocPerm", doc_name)
				else:
					d = frappe.new_doc("Custom DocPerm")
					d.parent = doctype
					d.role = role_name
					d.permlevel = permlevel

				d.select = p.get("select", 0)
				d.read = p.get("read", 0)
				d.write = p.get("write", 0)
				d.create = p.get("create", 0)
				d.delete = p.get("delete", 0)
				d.submit = p.get("submit", 0)
				d.amend = p.get("amend", 0)
				d.cancel = p.get("cancel", 0)
				d.if_owner = p.get("if_owner", 0)
				d.print = p.get("print", 1)
				d.email = p.get("email", 1)
				d.export = p.get("export", 1)
				d.report = p.get("report", 1)
				d.share = p.get("share", 1)
				d.save()
				updated_doctypes.append(doctype)  # Append doctype on successful update
			except Exception as e:
				print(f"Skipping {doctype}: {e}")

		if updated_doctypes:  # Print consolidated message after all permissions for a role are processed
			print(f"Updated permissions for {role_name} on: [{', '.join(updated_doctypes)}]")
