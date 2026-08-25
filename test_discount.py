import frappe
frappe.init(site="zap.localhost")
frappe.connect()
inv = frappe.get_all("Sales Invoice", filters={"docstatus": 1, "is_pos": 0}, order_by="creation desc", limit=1)[0]
doc = frappe.get_doc("Sales Invoice", inv.name)
doc.db_set({"apply_discount_on": "Grand Total", "discount_amount": 68.0})
frappe.db.commit()
doc.reload()
print(f"discount_amount: {doc.discount_amount}, apply: {doc.apply_discount_on}")
html = frappe.get_print("Sales Invoice", doc.name, print_format="GST Invoice - Original for Receiver")
print("HTML contains discount:", "Additional Discount" in html)
