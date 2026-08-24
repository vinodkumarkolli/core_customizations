import frappe
import json
import re

def remove_custom_sales_person():
    frappe.init(site="zap.localhost")
    frappe.connect()

    # 1. Delete Custom Fields
    for dt in ["Sales Order", "Sales Invoice"]:
        name = f"{dt}-custom_sales_person"
        if frappe.db.exists("Custom Field", name):
            frappe.delete_doc("Custom Field", name, ignore_permissions=True)
            print(f"Deleted custom field {name}")

    # 2. Update Print Formats
    print_formats = frappe.get_all("Print Format", filters={"module": "Core Customizations"})
    for pf in print_formats:
        doc = frappe.get_doc("Print Format", pf.name)
        if doc.html and "doc.custom_sales_person" in doc.html:
            # Regex to match the block:
            # {% if doc.custom_sales_person %}
            #     {% set sp_name = frappe.db.get_value("User", doc.custom_sales_person, "full_name") or doc.custom_sales_person %}
            #     <b>Sales Person:</b> {{ sp_name }}
            # {% endif %}
            
            # Since it's Jinja, we can just replace it with empty string
            block_to_remove = r"{% if doc\.custom_sales_person %}.*?{% endif %}"
            new_html = re.sub(block_to_remove, "", doc.html, flags=re.DOTALL)
            
            doc.html = new_html
            doc.save()
            print(f"Updated Print Format {pf.name}")

    frappe.db.commit()

remove_custom_sales_person()
