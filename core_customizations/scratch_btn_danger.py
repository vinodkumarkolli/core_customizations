import frappe

def fix_delete_btn_color():
    frappe.init(site="zap.localhost")
    frappe.connect()

    dn_script = frappe.get_doc("Client Script", {"dt": "Delivery Note", "view": "Form"})
    script = dn_script.script
    
    old_str = "d.$wrapper.find(\".modal-footer .btn-default\").removeClass(\"btn-default\").addClass(\"btn-danger\");"
    
    new_str = "d.$wrapper.find('.modal-footer button:contains(\"' + __('Delete All Packing Slips') + '\")').removeClass('btn-default btn-light btn-secondary').addClass('btn-danger');"
    
    if old_str in script:
        dn_script.script = script.replace(old_str, new_str)
        dn_script.save()
        frappe.db.commit()
        print("Successfully updated Delete All button CSS in DB")
    else:
        print("String not found in Delivery Note Client Script")

fix_delete_btn_color()
