import re

import frappe

MOBILE = re.compile(r"[6-9]\d{9}")
LANDLINE = re.compile(r"[1-5]\d{9}")


def normalise(raw):
    """Return +91XXXXXXXXXX for Indian mobiles and STD landlines.

    Anything else (blank, text, several numbers, another country code,
    wrong length) is returned unchanged, never guessed."""
    if raw is None:
        return raw
    s = str(raw).strip()
    if not s or re.search(r"[A-Za-z/,;]", s):
        return raw
    d = re.sub(r"[\s\-\.\(\)]", "", s)

    if d.startswith("+91"):
        rest = d[3:]
    elif d.startswith("0091"):
        rest = d[4:]
    elif d.startswith("91") and len(d) == 12:
        rest = d[2:]
    elif d.startswith("0") and len(d) == 11:
        rest = d[1:]
    elif d.startswith("+"):
        return raw  # another country code
    else:
        rest = d

    if MOBILE.fullmatch(rest):
        return "+91" + rest
    # landlines only when the number came with an STD/country prefix
    if d.startswith(("0", "+91", "91")) and LANDLINE.fullmatch(rest):
        return "+91" + rest
    return raw


def is_indian_mobile(value):
    return bool(value) and bool(re.fullmatch(r"\+91[6-9]\d{9}", str(value)))


def normalise_lead(doc, method=None):
    for field in ("mobile_no", "phone"):
        if doc.get(field):
            doc.set(field, normalise(doc.get(field)))


def normalise_contact(doc, method=None):
    # parent fields (used when there are no child rows)
    for field in ("mobile_no", "phone"):
        if doc.get(field):
            doc.set(field, normalise(doc.get(field)))

    rows = doc.get("phone_nos") or []
    for row in rows:
        if row.phone:
            row.phone = normalise(row.phone)

    # A Contact with no primary mobile but a valid Indian mobile in its
    # numbers gets that number marked as the primary mobile, so
    # mobile_no (derived from the primary row) is filled in.
    if rows and not any(r.get("is_primary_mobile_no") for r in rows):
        for row in rows:
            if is_indian_mobile(row.phone):
                row.is_primary_mobile_no = 1
                break