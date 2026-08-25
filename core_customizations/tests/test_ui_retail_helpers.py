import frappe

from core_customizations.tests.test_pos_dual_workflow import TestPOSDualWorkflow


@frappe.whitelist()
def setup_cypress_retail_data():
	if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
		frappe.throw("Not allowed")

	frappe.set_user("Administrator")

	# We can just instantiate the test class and call setup manually
	# or just replicate its minimal setup
	company = frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1)[0].name

	pos_profile_name = "_Test POS Profile"
	warehouse = "Stores - SE-K"
	if not frappe.db.exists("Warehouse", warehouse):
		whs = frappe.get_all("Warehouse", filters={"company": company, "is_group": 0}, limit=1)
		if whs:
			warehouse = whs[0].name

	customer = "_Test POS Customer"
	if not frappe.db.exists("Customer", customer):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": customer,
				"customer_group": "Commercial",
				"territory": "All Territories",
				"default_price_list": "Standard Selling",
			}
		).insert(ignore_permissions=True)

	item_code = "_Test_POS_Item"
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": "Test POS Item",
				"item_group": "Products",
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)

	# Setup POS profile
	if not frappe.db.exists("POS Profile", pos_profile_name):
		cash_account = frappe.db.get_value("Account", {"account_type": "Cash", "company": company}, "name")
		if not cash_account:
			cash_account = frappe.db.get_value("Account", {"is_group": 0, "company": company}, "name")

		cost_center = frappe.db.get_value("Company", company, "cost_center")
		if not cost_center:
			ccs = frappe.get_all("Cost Center", filters={"company": company, "is_group": 0}, limit=1)
			cost_center = ccs[0].name if ccs else None

		pos_prof = frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": pos_profile_name,
				"company": company,
				"warehouse": warehouse,
				"customer": customer,
				"write_off_account": cash_account,
				"write_off_cost_center": cost_center,
				"cost_center": cost_center,
				"payments": [{"mode_of_payment": "Cash", "default": 1, "account": cash_account}],
			}
		)
		pos_prof.insert(ignore_permissions=True)

	# Setup Opening Entry
	existing = frappe.get_all(
		"POS Opening Entry",
		filters={"pos_profile": pos_profile_name, "status": "Open", "docstatus": 1},
		limit=1,
	)
	if not existing:
		entry = frappe.get_doc(
			{
				"doctype": "POS Opening Entry",
				"period_start_date": frappe.utils.nowdate(),
				"pos_profile": pos_profile_name,
				"user": frappe.session.user,
				"company": company,
				"balance_details": [{"mode_of_payment": "Cash", "opening_amount": 1000}],
			}
		).insert(ignore_permissions=True)
		entry.submit()

	return {"pos_profile": pos_profile_name, "customer": customer, "item_code": item_code}


@frappe.whitelist()
def cleanup_cypress_retail_data():
	if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
		frappe.throw("Not allowed")

	frappe.set_user("Administrator")
	# [Ruff F841 Fix] Removed unused variable 'pos_profile_name = "_Test POS Profile"'

	# Cancel any open/closing entries and POS invoices
	# We skip strict cleanup here as Frappe test DBs are ephemeral,
	# but we can try to cancel the most recent ones.
	pass
