import frappe

def fix_dn_script():
    frappe.init(site="zap.localhost")
    frappe.connect()

    dn_script = frappe.get_doc("Client Script", {"dt": "Delivery Note", "view": "Form"})
    script = dn_script.script
    
    old_str = "let action_btns = `<a href=\"/printview?doctype=Packing%20Slip&name=${s.name}&trigger_print=1&format=Carton%20Shipping%20Label%20(4x6)&no_letterhead=1\" target=\"_blank\" class=\"btn btn-xs btn-default\" title=\"${__('Print Box')}\" style=\"margin-right: 4px;\">${__('Print')}</a>`;\n\t\t\t\tif (s.docstatus === 0) {"
    
    new_str = """let action_btns = "";
\t\t\t\tif (s.docstatus !== 0) {
\t\t\t\t\taction_btns += `<a href="/printview?doctype=Packing%20Slip&name=${s.name}&trigger_print=1&format=Carton%20Shipping%20Label%20(4x6)&no_letterhead=1" target="_blank" class="btn btn-xs btn-default" title="${__('Print Box')}" style="margin-right: 4px;">${__('Print')}</a>`;
\t\t\t\t}
\t\t\t\tif (s.docstatus === 0) {"""
    
    if old_str in script:
        dn_script.script = script.replace(old_str, new_str)
        dn_script.save()
        frappe.db.commit()
        print("Successfully updated Delivery Note Client Script in DB")
    else:
        print("String not found in Delivery Note Client Script")

fix_dn_script()
