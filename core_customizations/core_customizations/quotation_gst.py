import frappe

SKIP = ("name", "parent", "parentfield", "parenttype", "idx", "creation",
        "modified", "owner", "modified_by", "docstatus", "doctype")

def apply_gst_template(doc, method=None):
    """Fill GST rows from the named template when the quotation has none.
    Actual-type rows (the freight row) do not count as GST rows."""
    if not doc.taxes_and_charges:
        return
    if any(t.charge_type != "Actual" for t in (doc.get("taxes") or [])):
        return
    tpl = frappe.get_doc("Sales Taxes and Charges Template", doc.taxes_and_charges)
    for row in tpl.taxes:
        d = row.as_dict()
        for k in SKIP:
            d.pop(k, None)
        doc.append("taxes", d)
