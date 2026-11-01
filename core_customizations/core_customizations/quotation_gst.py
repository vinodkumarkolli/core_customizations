import re

import frappe

# Pincode prefix -> state. Longest prefix wins. Only clear-cut ranges are listed;
# anything not listed is treated as "not home state" and left for review.
PREFIX_STATE = {
    "11": "Delhi", "160": "Chandigarh", "12": "Haryana", "13": "Haryana",
    "14": "Punjab", "15": "Punjab", "17": "Himachal Pradesh",
    "30": "Rajasthan", "31": "Rajasthan", "32": "Rajasthan", "33": "Rajasthan", "34": "Rajasthan",
    "36": "Gujarat", "37": "Gujarat", "38": "Gujarat", "39": "Gujarat",
    "40": "Maharashtra", "41": "Maharashtra", "42": "Maharashtra", "43": "Maharashtra",
    "44": "Maharashtra", "403": "Goa",
    "50": "Telangana",
    "51": "Andhra Pradesh", "52": "Andhra Pradesh", "53": "Andhra Pradesh",
    "533464": "Puducherry",
    "56": "Karnataka", "57": "Karnataka", "58": "Karnataka", "59": "Karnataka",
    "60": "Tamil Nadu", "61": "Tamil Nadu", "62": "Tamil Nadu", "63": "Tamil Nadu", "64": "Tamil Nadu",
    "605": "Puducherry", "609602": "Puducherry", "609603": "Puducherry", "609604": "Puducherry",
    "609605": "Puducherry", "609606": "Puducherry", "609607": "Puducherry",
    "609608": "Puducherry", "609609": "Puducherry",
    "67": "Kerala", "68": "Kerala", "69": "Kerala", "673310": "Puducherry",
    "70": "West Bengal", "71": "West Bengal", "72": "West Bengal", "73": "West Bengal",
    "75": "Odisha", "76": "Odisha", "77": "Odisha",
}

SKIP = ("name", "parent", "parentfield", "parenttype", "idx", "creation",
        "modified", "owner", "modified_by", "docstatus", "doctype")


def state_from_pincode(pincode):
    for n in range(len(pincode), 1, -1):
        state = PREFIX_STATE.get(pincode[:n])
        if state:
            return state
    return None


def _lead_address_pincode(doc):
    lead = None
    if doc.quotation_to == "CRM Lead":
        lead = doc.party_name
    elif doc.quotation_to == "CRM Deal":
        lead = frappe.db.get_value("CRM Deal", doc.party_name, "lead")
    if not lead:
        return None
    text = frappe.db.get_value("CRM Lead", lead, "company_description") or ""
    for line in text.splitlines():
        if line.strip().lower().startswith("address:"):
            pins = re.findall(r"(?<!\d)[1-9]\d{5}(?!\d)", line)
            if pins:
                return pins[-1]
    return None


def _template(company, category):
    return frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"company": company, "tax_category": category, "disabled": 0}, "name")


def _set_place_of_supply(doc, state):
    try:
        from india_compliance.gst_india.constants import STATE_NUMBERS
        doc.place_of_supply = f"{STATE_NUMBERS[state]}-{state}"
    except Exception:
        frappe.logger("quotation_gst").info(f"place_of_supply not set for {state}")


def apply_gst(doc, method=None):
    # 1. Decide in-state / out-state from the delivery pincode, only when the
    #    quotation has no address of its own (India Compliance handles those).
    has_gst_rows = any(t.charge_type != "Actual" for t in (doc.get("taxes") or []))
    if not has_gst_rows and not (doc.get("shipping_address") or doc.get("customer_address")):
        pincode = _lead_address_pincode(doc)
        if pincode:
            state = state_from_pincode(pincode)
            home_code = (doc.get("company_gstin") or "")[:2] or "33"
            in_state = state == "Tamil Nadu" if home_code == "33" else False
            tpl = _template(doc.company, "In-State" if in_state else "Out-State")
            if tpl:
                doc.taxes_and_charges = tpl
            if state:
                _set_place_of_supply(doc, state)

    # 2. Fill GST rows from the template when there are none.
    #    Actual-type rows (freight) do not count as GST rows.
    if doc.get("taxes_and_charges") and not has_gst_rows:
        tpl_doc = frappe.get_doc("Sales Taxes and Charges Template", doc.taxes_and_charges)
        for row in tpl_doc.taxes:
            d = row.as_dict()
            for k in SKIP:
                d.pop(k, None)
            doc.append("taxes", d)