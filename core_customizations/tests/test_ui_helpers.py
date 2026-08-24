import frappe
from core_customizations.tests.test_delivery_note_workflow import setup_test_data, create_test_delivery_note

@frappe.whitelist()
def setup_cypress_test_delivery_note():
    # Only allow in development/test
    if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
        frappe.throw("Not allowed")
    
    frappe.set_user("Administrator")
    setup_test_data()
    
    dn = create_test_delivery_note("Cypress Test Item 1", 100, warehouse="Stores - SE-K")
    return dn.name

@frappe.whitelist()
def cleanup_cypress_test_data(dn_name):
    if frappe.conf.get("developer_mode") != 1 and frappe.conf.get("allow_tests") != 1:
        frappe.throw("Not allowed")
        
    frappe.set_user("Administrator")
    
    # Delete packing slips for this DN
    ps_list = frappe.get_all("Packing Slip", filters={"delivery_note": dn_name})
    for ps in ps_list:
        frappe.delete_doc("Packing Slip", ps.name, force=1)
        
    frappe.delete_doc("Delivery Note", dn_name, force=1)
    
    return "OK"
