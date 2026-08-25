import frappe


def setup_cypress_test_data():
	if not frappe.db.exists("Customer", "Cypress Customer"):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "Cypress Customer",
				"customer_group": "Commercial",
				"territory": "All Territories",
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Item", "Cypress Test Item 1"):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "Cypress Test Item 1",
				"item_name": "Cypress Test Item 1",
				"item_group": "Products",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"gst_hsn_code": "30049011",
			}
		).insert(ignore_permissions=True)


def create_test_delivery_note(item_code, qty, warehouse=None):
	company = frappe.defaults.get_user_default("company") or frappe.get_all("Company")[0].name
	dn = frappe.get_doc(
		{
			"doctype": "Delivery Note",
			"customer": "Cypress Customer",
			"company": company,
			"items": [{"item_code": item_code, "qty": qty, "uom": "Nos", "warehouse": warehouse}],
		}
	)
	dn.insert(ignore_permissions=True)
	return dn


@frappe.whitelist()
def setup_cypress_test_delivery_note():
	if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
		frappe.throw("Not allowed")

	frappe.set_user("Administrator")
	setup_cypress_test_data()

	dn = create_test_delivery_note("Cypress Test Item 1", 100, warehouse="Stores - SE-K")
	return dn.name


@frappe.whitelist()
def cleanup_cypress_test_data(dn_name):
	if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
		frappe.throw("Not allowed")

	frappe.set_user("Administrator")

	ps_list = frappe.get_all("Packing Slip", filters={"delivery_note": dn_name})
	for ps in ps_list:
		frappe.delete_doc("Packing Slip", ps.name, force=1)

	frappe.delete_doc("Delivery Note", dn_name, force=1)

	return "OK"
