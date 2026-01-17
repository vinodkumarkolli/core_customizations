import frappe

def execute():
	role_name = "Field Sales User"
	if not frappe.db.exists("Role", role_name):
		role = frappe.new_doc("Role")
		role.role_name = role_name
		role.desk_access = 1
		role.save()

	permissions = [
		{"parent": "Warehouse", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Incoterm", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Company", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Department", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "POS Profile", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "POS Invoice Merge Log", "read": 1, "write": 1, "create": 1, "delete": 1},
		{"parent": "Appointment", "read": 1, "write": 1, "create": 1, "delete": 0},
		{"parent": "Warehouse Type", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "POS Settings", "read": 1, "write": 1, "create": 0, "delete": 0},
		{"parent": "POS Profile", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Shipping Rule", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Stock Settings", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Currency Exchange", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Product Bundle", "read": 1, "write": 1, "create": 1, "delete": 1},
		{"parent": "Customer", "read": 1, "write": 1, "create": 1, "delete": 0},
		{"parent": "Delivery Note", "read": 1, "write": 1, "create": 1, "delete": 1},
		{"parent": "Item", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Installation Note", "read": 1, "write": 1, "create": 1, "delete": 1},
		{"parent": "Sales Partner", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Packing Slip", "read": 1, "write": 1, "create": 1, "delete": 1},
		{"parent": "Item Group", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Brand", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Account", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Currency", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Price List", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Cost Center", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Fiscal Year", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Address", "read": 1, "write": 1, "create": 1, "delete": 0},
		{"parent": "Contact", "read": 1, "write": 1, "create": 1, "delete": 0},
		{"parent": "Bin", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Sales Person", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Terms and Conditions", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Territory", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "UOM", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Batch", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Customer Group", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Campaign", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Designation", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Sales Taxes and Charges Template", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Industry Type", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Stock Closing Entry", "read": 1, "write": 1, "create": 1, "delete": 1},
		{"parent": "Stock Closing Balance", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Serial and Batch Bundle", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "amend": 0, "cancel": 0, "if_owner": 1, "print": 1, "email": 1, "export": 1, "report": 0, "share": 1},
		{"parent": "Stock Entry Type", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Stock Entry", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Stock Ledger Entry", "read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Accounts Settings","read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Stock Settings","read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Project","read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Mode of Payment","read": 1, "write": 0, "create": 0, "delete": 0},
		{"parent": "Task","read": 1, "write": 0, "create": 0, "delete": 0, "submit": 0, "amend": 0, "cancel": 0, "if_owner": 0, "print": 1, "email": 1, "export": 1, "report": 0, "share": 1},
		{"parent": "Task","read": 1, "write": 1, "create": 1, "delete": 0, "submit": 1, "amend": 1, "cancel": 1, "if_owner": 1, "print": 1, "email": 1, "export": 1, "report": 0, "share": 1},
		{"parent": "POS Closing Entry", "read": 1, "write": 1, "create": 1, "delete": 0, "submit": 1, "amend": 0, "cancel": 0, "if_owner": 1, "print": 1, "email": 1, "export": 1, "report": 0, "share": 1},
		{"parent": "POS Opening Entry", "read": 1, "write": 1, "create": 1, "delete": 0, "submit": 1, "amend": 0, "cancel": 0, "if_owner": 1, "print": 1, "email": 1, "export": 1, "report": 0, "share": 1},
		{"parent": "Sales Invoice", "read": 1, "write": 1, "create": 1, "delete": 0, "submit": 1, "amend": 0, "cancel": 0, "if_owner": 1, "print": 1, "email": 1, "export": 1, "report": 0, "share": 1},
		{"parent": "POS Invoice", "read": 1, "write": 1, "create": 1, "delete": 0, "submit": 1, "amend": 0, "cancel": 0, "if_owner": 1, "print": 1, "email": 1, "export": 1, "report": 0, "share": 1},
		{"parent": "point-of-sale", "page": 1}
	]

	for p in permissions:
		if p.get("page"):
			page_name = p["parent"]
			if not frappe.db.exists("Page", page_name):
				print(f"Page {page_name} not found.")
				continue

			# Check if Custom Role exists
			custom_role_name = frappe.db.get_value("Custom Role", {"page": page_name})
			
			if custom_role_name:
				custom_role = frappe.get_doc("Custom Role", custom_role_name)
				existing_roles = [r.role for r in custom_role.roles]
				
				if role_name not in existing_roles:
					custom_role.append("roles", {"role": role_name})
					custom_role.save()
					print(f"Added '{role_name}' to Custom Role for '{page_name}'.")
				else:
					print(f"Role '{role_name}' already has access to '{page_name}' via Custom Role.")
			else:
				# Create new Custom Role with existing standard roles + new role
				page_doc = frappe.get_doc("Page", page_name)
				roles = [{"role": r.role} for r in page_doc.roles]
				
				# Avoid duplicates if role is already in standard roles
				if not any(r["role"] == role_name for r in roles):
					roles.append({"role": role_name})
				
				custom_role = frappe.new_doc("Custom Role")
				custom_role.page = page_name
				custom_role.set("roles", roles)
				custom_role.save()
				print(f"Created Custom Role for '{page_name}' with role '{role_name}'.")
			continue

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
			doc_name = frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role_name, "permlevel": 0})
			if doc_name:
				d = frappe.get_doc("Custom DocPerm", doc_name)
			else:
				d = frappe.new_doc("Custom DocPerm")
				d.parent = doctype
				d.role = role_name
				d.permlevel = 0

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
		except Exception as e:
			print(f"Skipping {doctype}: {e}")

	# Ignore user permissions for Stock Settings fields
	stock_settings_fields = ["default_warehouse", "sample_retention_warehouse"]
	for field in stock_settings_fields:
		if not frappe.db.exists("Property Setter", {"doc_type": "Stock Settings", "field_name": field, "property": "ignore_user_permissions"}):
			frappe.make_property_setter({
				"doctype": "Stock Settings",
				"doctype_or_field": "DocField",
				"field_name": field,
				"property": "ignore_user_permissions",
				"property_type": "Check",
				"value": "1"
			})

