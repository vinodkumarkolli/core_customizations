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
		],
		"Field Sales User": [
			# Group 1: Read, Print, Email, Report, Export, Share (Basic Read+)
			{"parent": "Warehouse", "read": 1},
			{"parent": "Incoterm", "read": 1},
			{"parent": "Company", "read": 1},
			{"parent": "Department", "read": 1},
			{"parent": "POS Profile", "read": 1},
			{"parent": "Warehouse Type", "read": 1},
			{"parent": "Shipping Rule", "read": 1},
			{"parent": "Stock Settings", "read": 1},
			{"parent": "Currency Exchange", "read": 1},
			{"parent": "Item", "read": 1},
			{"parent": "Sales Partner", "read": 1},
			{"parent": "Item Group", "read": 1},
			{"parent": "Brand", "read": 1},
			{"parent": "Account", "read": 1},
			{"parent": "Currency", "read": 1},
			{"parent": "Price List", "read": 1},
			{"parent": "Cost Center", "read": 1},
			{"parent": "Fiscal Year", "read": 1},
			{"parent": "Bin", "read": 1},
			{"parent": "Sales Person", "read": 1},
			{"parent": "Terms and Conditions", "read": 1},
			{"parent": "Territory", "read": 1},
			{"parent": "UOM", "read": 1},
			{"parent": "Batch", "read": 1},
			{"parent": "Customer Group", "read": 1},
			{"parent": "Campaign", "read": 1},
			{"parent": "Designation", "read": 1},
			{"parent": "Sales Taxes and Charges Template", "read": 1},
			{"parent": "Industry Type", "read": 1},
			{"parent": "Stock Closing Balance", "read": 1},
			{"parent": "Stock Entry Type", "read": 1},
			{"parent": "Stock Entry", "read": 1},
			{"parent": "Stock Ledger Entry", "read": 1},
			{"parent": "Accounts Settings", "read": 1},
			{"parent": "Project", "read": 1},
			{"parent": "Mode of Payment", "read": 1},
			{"parent": "Stock Settings","read":1},

			# Group 2: Read, Write, Create, Delete
			{"parent": "POS Invoice Merge Log", "read": 1, "write": 1, "create": 1, "delete": 1},
			{"parent": "Appointment", "read": 1, "write": 1, "create": 1, "delete": 1},

			# Group 3: Read, Write, Create
			{"parent": "Product Bundle", "read": 1, "write": 1, "create": 1},

			# Group 4: Read, Write
			{"parent": "POS Settings", "read": 1, "write": 1},

			# Group 5: Read, Write, Create, Submit
			{"parent": "Delivery Note", "read": 1, "write": 1, "create": 1, "submit": 1},
			{"parent": "Installation Note", "read": 1, "write": 1, "create": 1, "submit": 1},
			{"parent": "Packing Slip", "read": 1, "write": 1, "create": 1, "submit": 1},
			{"parent": "Stock Closing Entry", "read": 1, "write": 1, "create": 1, "submit": 1},

			# Group 6: Read, Write, Create (Address and Contact)
			{"parent": "Address", "read": 1, "write": 1, "create": 1},
			{"parent": "Contact", "read": 1, "write": 1, "create": 1},

			# Group 8: Special Cases with 'Only If Creator' (if_owner)
			{"parent": "Serial and Batch Bundle", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "if_owner": 1},
			{"parent": "POS Closing Entry", "read": 1, "write": 1, "create": 1, "submit": 1, "if_owner": 1},
			{"parent": "POS Opening Entry", "read": 1, "write": 1, "create": 1, "submit": 1, "if_owner": 1},
			{"parent": "Sales Invoice", "read": 1, "write": 1, "create": 1, "submit": 1, "if_owner": 1},
			{"parent": "POS Invoice", "read": 1, "write": 1, "create": 1, "submit": 1, "if_owner": 1},
			{"parent": "Task", "read": 1, "write": 1, "create": 1, "if_owner": 1},

			# Special Case: Customer (Select, Read, Write, Create)
			{"parent": "Customer", "select": 1, "read": 1, "write": 1, "create": 1},
		]
	}
	# We need to create a new role called "Field Sales User" if it doesn't exist
	if not frappe.db.exists("Role", "Field Sales User"):
		d = frappe.new_doc("Role")
		d.role_name = "Field Sales User"
		d.insert()
		print("Created role: Field Sales User")
	# We need to add permissions to the "Field Sales User" role

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
