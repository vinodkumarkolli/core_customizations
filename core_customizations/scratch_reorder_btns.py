import frappe

def reorder_buttons():
    frappe.init(site="zap.localhost")
    frappe.connect()

    dn_script = frappe.get_doc("Client Script", {"dt": "Delivery Note", "view": "Form"})
    script = dn_script.script
    
    # We replace from 'let action_btns = "";' all the way down to 'html +='
    old_str = """let action_btns = "";
\t\t\t\tif (s.docstatus !== 0) {
\t\t\t\t\taction_btns += `<a href="/printview?doctype=Packing%20Slip&name=${s.name}&trigger_print=1&format=Carton%20Shipping%20Label%20(4x6)&no_letterhead=1" target="_blank" class="btn btn-xs btn-default" title="${__('Print Box')}" style="margin-right: 4px;">${__('Print')}</a>`;
\t\t\t\t}
\t\t\t\tif (s.docstatus === 0) {
\t\t\t\t\taction_btns += `
\t\t\t\t\t\t<button class="btn btn-xs btn-danger delete-single-ps" data-ps="${s.name}" title="${__('Delete Box')}">
\t\t\t\t\t\t\t${__('Delete')}
\t\t\t\t\t\t</button>
\t\t\t\t\t\t<button class="btn btn-xs btn-primary submit-single-ps" data-ps="${s.name}" title="${__('Submit Box')}" style="margin-left: 4px;">
\t\t\t\t\t\t\t${__('Submit')}
\t\t\t\t\t\t</button>
\t\t\t\t\t`;
\t\t\t\t} else if (s.docstatus === 1) {
\t\t\t\t\taction_btns += `
\t\t\t\t\t\t<button class="btn btn-xs btn-warning cancel-single-ps" data-ps="${s.name}" title="${__('Cancel Box')}" style="color: #975a16; background-color: #feebc8; border-color: #fbd38d;">
\t\t\t\t\t\t\t${__('Cancel')}
\t\t\t\t\t\t</button>
\t\t\t\t\t`;
\t\t\t\t} else if (s.docstatus === 2) {
\t\t\t\t\taction_btns += `
\t\t\t\t\t\t<button class="btn btn-xs btn-danger delete-single-ps" data-ps="${s.name}" title="${__('Delete Box')}">
\t\t\t\t\t\t\t${__('Delete')}
\t\t\t\t\t\t</button>
\t\t\t\t\t`;
\t\t\t\t}

\t\t\t\thtml +="""
    
    new_str = """let action_btns = "";
\t\t\t\tif (s.docstatus === 0) {
\t\t\t\t\taction_btns += `
\t\t\t\t\t\t<button class="btn btn-xs btn-danger delete-single-ps" data-ps="${s.name}" title="${__('Delete Box')}">
\t\t\t\t\t\t\t${__('Delete')}
\t\t\t\t\t\t</button>
\t\t\t\t\t\t<button class="btn btn-xs btn-primary submit-single-ps" data-ps="${s.name}" title="${__('Submit Box')}" style="margin-left: 4px;">
\t\t\t\t\t\t\t${__('Submit')}
\t\t\t\t\t\t</button>
\t\t\t\t\t`;
\t\t\t\t} else if (s.docstatus === 1) {
\t\t\t\t\taction_btns += `
\t\t\t\t\t\t<button class="btn btn-xs btn-danger cancel-single-ps" data-ps="${s.name}" title="${__('Cancel Box')}" style="margin-right: 4px;">
\t\t\t\t\t\t\t${__('Cancel')}
\t\t\t\t\t\t</button>
\t\t\t\t\t\t<a href="/printview?doctype=Packing%20Slip&name=${s.name}&trigger_print=1&format=Carton%20Shipping%20Label%20(4x6)&no_letterhead=1" target="_blank" class="btn btn-xs btn-primary" title="${__('Print Box')}">${__('Print')}</a>
\t\t\t\t\t`;
\t\t\t\t} else if (s.docstatus === 2) {
\t\t\t\t\taction_btns += `
\t\t\t\t\t\t<button class="btn btn-xs btn-danger delete-single-ps" data-ps="${s.name}" title="${__('Delete Box')}" style="margin-right: 4px;">
\t\t\t\t\t\t\t${__('Delete')}
\t\t\t\t\t\t</button>
\t\t\t\t\t\t<a href="/printview?doctype=Packing%20Slip&name=${s.name}&trigger_print=1&format=Carton%20Shipping%20Label%20(4x6)&no_letterhead=1" target="_blank" class="btn btn-xs btn-primary" title="${__('Print Box')}">${__('Print')}</a>
\t\t\t\t\t`;
\t\t\t\t}

\t\t\t\thtml +="""
    
    if old_str in script:
        dn_script.script = script.replace(old_str, new_str)
        dn_script.save()
        frappe.db.commit()
        print("Successfully reordered buttons in Delivery Note Client Script in DB")
    else:
        print("String not found in Delivery Note Client Script")

reorder_buttons()
