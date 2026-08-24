import frappe

def add_disclaimer():
    frappe.init(site="zap.localhost")
    frappe.connect()

    dn_script = frappe.get_doc("Client Script", {"dt": "Delivery Note", "view": "Form"})
    script = dn_script.script
    
    old_str = "html += `</tbody></table></div>`;\n\n\t\t\td.fields_dict.slips_table_html.$wrapper.html(html);"
    
    new_str = """html += `</tbody></table></div>`;
\t\t\thtml += `
\t\t\t\t<div style="margin-top: 10px; font-size: 11.5px; color: #718096;">
\t\t\t\t\t<i class="fa fa-info-circle text-muted"></i> <i><b>Note:</b> Draft Packing Slips cannot be printed. Please submit them first.</i>
\t\t\t\t</div>
\t\t\t`;

\t\t\td.fields_dict.slips_table_html.$wrapper.html(html);"""
    
    if old_str in script:
        dn_script.script = script.replace(old_str, new_str)
        dn_script.save()
        frappe.db.commit()
        print("Successfully added disclaimer to Delivery Note Client Script in DB")
    else:
        print("String not found in Delivery Note Client Script")

add_disclaimer()
