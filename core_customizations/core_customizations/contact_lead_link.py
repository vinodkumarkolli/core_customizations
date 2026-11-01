import re

import frappe

VALID = re.compile(r"\+91[6-9]\d{9}")


def _valid(*values):
    return {v.strip() for v in values if v and VALID.fullmatch(v.strip())}


def _contact_numbers(contact):
    """Valid +91 numbers on a Contact doc, from its fields and its number rows."""
    nums = _valid(contact.get("mobile_no"), contact.get("phone"))
    for r in contact.get("phone_nos") or []:
        nums |= _valid(r.phone)
    return nums


def _leads_for_numbers(numbers):
    if not numbers:
        return set()
    return set(frappe.get_all(
        "CRM Lead",
        or_filters=[["mobile_no", "in", list(numbers)], ["phone", "in", list(numbers)]],
        pluck="name"))


def _contacts_for_number(number):
    names = set(frappe.get_all(
        "Contact", or_filters=[["mobile_no", "=", number], ["phone", "=", number]], pluck="name"))
    names |= set(frappe.get_all(
        "Contact Phone", filters={"phone": number, "parenttype": "Contact"}, pluck="parent"))
    return names


def _already_linked(contact_name):
    return frappe.db.exists("Dynamic Link", {
        "parenttype": "Contact", "parent": contact_name, "link_doctype": "CRM Lead"})


def link_for_number(number):
    """Background job: link every Contact on this number to its one Lead."""
    for contact_name in _contacts_for_number(number):
        if _already_linked(contact_name):
            continue
        contact = frappe.get_doc("Contact", contact_name)
        leads = _leads_for_numbers(_contact_numbers(contact))
        if len(leads) != 1:      # none, or ambiguous: never guess
            continue
        contact.append("links", {"link_doctype": "CRM Lead", "link_name": leads.pop()})
        contact.flags.in_link_hook = True
        contact.save(ignore_permissions=True)


def _queue(numbers):
    for n in numbers:
        frappe.enqueue(
            "core_customizations.contact_lead_link.link_for_number",
            queue="short", number=n, enqueue_after_commit=True,
            job_id=f"contact_lead_link:{n}", deduplicate=True)


def on_lead_update(doc, method=None):
    _queue(_valid(doc.get("mobile_no"), doc.get("phone")))


def on_contact_update(doc, method=None):
    if doc.flags.get("in_link_hook"):
        return
    _queue(_contact_numbers(doc))