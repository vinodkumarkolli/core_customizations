import frappe

@frappe.whitelist()
def setup_cypress_3pl_data():
    if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
        frappe.throw("Not allowed")
    
    frappe.set_user("Administrator")
    
    if not frappe.db.exists("Item", "Cypress 3PL Item"):
        frappe.get_doc({
            "doctype": "Item",
            "item_code": "Cypress 3PL Item",
            "item_name": "Cypress 3PL Item",
            "item_group": "Products",
            "stock_uom": "Nos",
            "is_stock_item": 1,
            "custom_3pl_item": 1,
            "gst_hsn_code": "30049011"
        }).insert(ignore_permissions=True)
        
    if not frappe.db.exists("Supplier", "Cypress Supplier"):
        frappe.get_doc({
            "doctype": "Supplier",
            "supplier_name": "Cypress Supplier",
            "supplier_group": "Local"
        }).insert(ignore_permissions=True)
        
    return "OK"

@frappe.whitelist()
def cleanup_cypress_3pl_data():
    if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
        frappe.throw("Not allowed")
        
    frappe.set_user("Administrator")
    return "OK"
