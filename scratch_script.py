import frappe
import sys

def main():
    frappe.init(site="test.local")
    frappe.connect()
    
    invoices = frappe.get_all("Sales Invoice", filters={"docstatus": 1, "is_pos": 0}, order_by="creation desc", limit=1)
    if not invoices:
        print("No invoices found")
        sys.exit(0)
    
    inv = frappe.get_doc("Sales Invoice", invoices[0].name)
    inv.db_set("apply_discount_on", "Grand Total")
    inv.db_set("discount_amount", 68.0)
    frappe.db.commit()
    
    inv.reload()
    print(f"discount_amount: {inv.discount_amount}, apply_discount_on: {inv.apply_discount_on}")
    
    html = frappe.get_print("Sales Invoice", inv.name, print_format="GST Invoice - Original for Receiver")
    print(f"Contains 'Additional Discount:': {'Additional Discount:' in html}")
    print(f"Contains '68': {'68' in html}")
    if 'Additional Discount:' not in html:
        print(html)

if __name__ == "__main__":
    main()
