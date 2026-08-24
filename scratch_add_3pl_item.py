import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def add_custom_field():
    frappe.init(site="zap.localhost")
    frappe.connect()

    create_custom_field("Item", {
        "fieldname": "custom_3pl_item",
        "label": "Is 3PL Item",
        "fieldtype": "Check",
        "insert_after": "is_stock_item",
        "default": "0",
        "description": "If checked, this item must be received via Purchase Receipt before a Purchase Invoice can be created."
    })
    
    frappe.db.commit()
    print("Custom field custom_3pl_item added successfully.")

add_custom_field()
