import frappe

def validate_3pl_items(doc, method):
    """
    Validates that if a Purchase Invoice contains any 3PL Item (custom_3pl_item = 1):
    1. update_stock is not checked (it must be handled through PR).
    2. Every 3PL Item row has a linked Purchase Receipt.
    """
    item_codes = [item.item_code for item in doc.get("items")]
    if not item_codes:
        return
        
    item_data = frappe.get_all(
        "Item", 
        filters={"name": ("in", item_codes)}, 
        fields=["name", "custom_3pl_item"]
    )
    
    items_3pl = {row.name for row in item_data if row.custom_3pl_item}
    
    if not items_3pl:
        return
        
    if doc.update_stock:
        frappe.throw("3PL Items cannot update stock directly from a Purchase Invoice. Please use a Purchase Receipt.")
        
    for item in doc.get("items"):
        if item.item_code in items_3pl:
            if not item.purchase_receipt:
                frappe.throw(
                    f"Row #{item.idx}: 3PL Item '{item.item_code}' must be billed against a Purchase Receipt. Standalone Purchase Invoices are not allowed."
                )
