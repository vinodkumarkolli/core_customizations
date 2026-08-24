import frappe

def setup_cypress_test_data():
    if not frappe.db.exists("Customer", "Cypress Customer"):
        frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "Cypress Customer",
            "customer_group": "Commercial",
            "territory": "All Territories"
        }).insert(ignore_permissions=True)
        
    if not frappe.db.exists("Item", "Cypress Test Item 1"):
        frappe.get_doc({
            "doctype": "Item",
            "item_code": "Cypress Test Item 1",
            "item_name": "Cypress Test Item 1",
            "item_group": "Products",
            "stock_uom": "Nos",
            "is_stock_item": 1,
            "gst_hsn_code": "30049011"
        }).insert(ignore_permissions=True)

@frappe.whitelist()
def setup_cypress_wholesale_data():
    if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
        frappe.throw("Not allowed")
    
    frappe.set_user("Administrator")
    setup_cypress_test_data()
    
    # Create a submitted Sales Order
    company = frappe.defaults.get_user_default("company") or frappe.get_all("Company")[0].name
    so = frappe.get_doc({
        "doctype": "Sales Order",
        "customer": "Cypress Customer",
        "company": company,
        "delivery_date": frappe.utils.add_days(frappe.utils.nowdate(), 7),
        "items": [{
            "item_code": "Cypress Test Item 1",
            "qty": 100,
            "rate": 500
        }]
    })
    so.insert(ignore_permissions=True)
    so.submit()
    
    return so.name

@frappe.whitelist()
def cleanup_cypress_wholesale_data(so_name):
    if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
        frappe.throw("Not allowed")
        
    frappe.set_user("Administrator")
    
    si_list = frappe.get_all("Sales Invoice", filters={"items.sales_order": so_name})
    for si in si_list:
        doc = frappe.get_doc("Sales Invoice", si.name)
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Sales Invoice", si.name, force=1)
        
    dn_list = frappe.get_all("Delivery Note", filters={"items.against_sales_order": so_name})
    for dn in dn_list:
        doc = frappe.get_doc("Delivery Note", dn.name)
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Delivery Note", dn.name, force=1)
        
    so = frappe.get_doc("Sales Order", so_name)
    if so.docstatus == 1:
        so.cancel()
    frappe.delete_doc("Sales Order", so_name, force=1)
    
    return "OK"
