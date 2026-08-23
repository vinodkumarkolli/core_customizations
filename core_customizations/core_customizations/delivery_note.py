import re
import json
import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate
from frappe.contacts.doctype.address.address import get_address_display


def _get_formatted_address(address_name):
	"""
	Returns a clean multi-line plain text address display without raw HTML tags (<br>),
	guaranteeing inclusion of the GSTIN / Tax ID if available on the Address record.
	"""
	if not address_name or not frappe.db.exists("Address", address_name):
		return ""
	try:
		addr_doc = frappe.get_doc("Address", address_name)
		raw_html = get_address_display(addr_doc.as_dict()) or ""

		# Replace <br>, <br/>, <br /> with real newlines
		clean_text = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
		# Strip any other HTML tags
		clean_text = re.sub(r"<[^>]+>", "", clean_text)

		lines = [line.strip().rstrip(",") for line in clean_text.split("\n") if line.strip()]

		# Ensure GSTIN / Tax ID is present
		gstin = getattr(addr_doc, "gstin", None) or getattr(addr_doc, "tax_id", None)
		has_gstin = any("GSTIN" in line.upper() for line in lines)
		if gstin and not has_gstin:
			lines.append(f"GSTIN: {gstin}")

		return "\n".join(lines)
	except Exception:
		return ""


@frappe.whitelist()
def update_transporter_details(delivery_note, transporter=None, from_address=None, is_godown=0, to_address=None, lr_no=None, lr_date=None):
	"""
	Whitelisted method to update Transporter, Origin Hub, Godown Delivery,
	and Destination Godown fields on a Delivery Note in both Draft and Submitted states.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	dn = frappe.get_doc("Delivery Note", delivery_note)
	is_godown = 1 if cint(is_godown) else 0

	if is_godown:
		if not from_address:
			frappe.throw(_("Origin / Booking Hub Address is required before enabling Godown Delivery"))
		if not to_address:
			frappe.throw(_("Destination Godown Address is mandatory when Godown Delivery is enabled"))

	from_address_display = _get_formatted_address(from_address)
	to_address_display = _get_formatted_address(to_address) if is_godown else ""

	update_dict = {
		"custom_transporter": transporter or None,
		"custom_transporter_from_address": from_address or None,
		"custom_transporter_from_address_display": from_address_display,
		"custom_is_godown_delivery": is_godown,
		"custom_transporter_to_address": to_address if is_godown else None,
		"custom_transporter_to_address_display": to_address_display if is_godown else "",
		"lr_no": lr_no or None,
		"lr_date": getdate(lr_date) if lr_date else None,
	}

	# Update directly via db_set to support both draft and submitted documents
	for fieldname, value in update_dict.items():
		dn.db_set(fieldname, value, update_modified=True)

	frappe.db.commit()

	return {
		"message": _("Transporter details updated successfully"),
		"transporter": transporter,
		"from_address": from_address,
		"from_address_display": from_address_display,
		"is_godown_delivery": is_godown,
		"to_address": to_address if is_godown else None,
		"to_address_display": to_address_display if is_godown else "",
		"lr_no": lr_no,
		"lr_date": str(lr_date) if lr_date else None,
	}


@frappe.whitelist()
def update_lr_details(delivery_note, lr_no=None, lr_date=None):
	"""
	Whitelisted method to update Lorry Receipt (LR) number and date on a Delivery Note
	in both Draft and Submitted states.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	dn = frappe.get_doc("Delivery Note", delivery_note)

	dn.db_set("lr_no", lr_no or None, update_modified=True)
	dn.db_set("lr_date", getdate(lr_date) if lr_date else None, update_modified=True)
	frappe.db.commit()

	return {
		"message": _("LR Details updated successfully"),
		"lr_no": lr_no,
		"lr_date": str(lr_date) if lr_date else None,
	}


def validate_delivery_note(doc, method=None):
	"""
	Validates and auto-populates transporter defaults from Customer if not already set,
	and ensures address display fields are populated and sanitized.
	"""
	# 1. If customer is set and transporter is not set, auto-populate from customer defaults
	if doc.get("customer") and not doc.get("custom_transporter"):
		cust_doc = frappe.get_cached_doc("Customer", doc.customer)
		if cust_doc.get("custom_default_transporter"):
			doc.custom_transporter = cust_doc.get("custom_default_transporter")
			doc.custom_transporter_from_address = cust_doc.get("custom_default_transporter_from_address")
			doc.custom_is_godown_delivery = cint(cust_doc.get("custom_is_godown_delivery"))
			doc.custom_transporter_to_address = cust_doc.get("custom_default_transporter_to_address") if doc.custom_is_godown_delivery else None

	# 2. If is_godown_delivery is 0, ensure destination address is cleared
	if not doc.get("custom_is_godown_delivery"):
		doc.custom_transporter_to_address = None
		doc.custom_transporter_to_address_display = ""

	# 3. Auto-populate sanitized address display fields
	if doc.get("custom_transporter_from_address"):
		doc.custom_transporter_from_address_display = _get_formatted_address(doc.custom_transporter_from_address)
	else:
		doc.custom_transporter_from_address_display = ""

	if doc.get("custom_is_godown_delivery") and doc.get("custom_transporter_to_address"):
		doc.custom_transporter_to_address_display = _get_formatted_address(doc.custom_transporter_to_address)
	else:
		doc.custom_transporter_to_address_display = ""


def before_submit_delivery_note(doc, method=None):
	"""
	Automatically submits all linked Draft Packing Slips before the Delivery Note is submitted.
	"""
	draft_packing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": doc.name, "docstatus": 0},
		pluck="name",
		order_by="from_case_no asc",
	)

	for ps_name in draft_packing_slips:
		ps = frappe.get_doc("Packing Slip", ps_name)
		ps.flags.ignore_permissions = True
		ps.submit()


def on_cancel_delivery_note(doc, method=None):
	"""
	Automatically cancels all linked Submitted Packing Slips when the Delivery Note is cancelled.
	"""
	submitted_packing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": doc.name, "docstatus": 1},
		pluck="name",
		order_by="from_case_no desc",
	)

	for ps_name in submitted_packing_slips:
		ps = frappe.get_doc("Packing Slip", ps_name)
		ps.flags.ignore_permissions = True
		ps.cancel()


@frappe.whitelist()
def get_unpacked_items_summary(delivery_note):
	"""
	Returns a breakdown of Delivery Note items, total ordered quantities,
	already packed quantities across existing Packing Slips, and remaining unpacked balances.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	dn = frappe.get_doc("Delivery Note", delivery_note)

	# Fetch existing packing slips linked to this delivery note
	packing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": delivery_note, "docstatus": ["<", 2]},
		fields=["name", "from_case_no", "to_case_no", "creation"],
		order_by="from_case_no asc",
	)

	packed_map = {}
	max_case_no = 0

	for ps in packing_slips:
		max_case_no = max(max_case_no, cint(ps.to_case_no) or cint(ps.from_case_no) or 0)
		ps_items = frappe.get_all(
			"Packing Slip Item",
			filters={"parent": ps.name},
			fields=["item_code", "qty"],
		)
		for psi in ps_items:
			packed_map[psi.item_code] = packed_map.get(psi.item_code, 0.0) + flt(psi.qty)

	items_summary = []
	for item in dn.items:
		packed_qty = flt(packed_map.get(item.item_code, 0.0))
		remaining_qty = max(0.0, flt(item.qty) - packed_qty)

		# Fetch default case pack size if configured and column exists
		case_pack = 0
		if frappe.db.has_column("Item", "custom_case_pack_qty"):
			case_pack = frappe.db.get_value("Item", item.item_code, "custom_case_pack_qty") or 0

		items_summary.append({
			"item_code": item.item_code,
			"item_name": item.item_name or item.item_code,
			"description": item.description,
			"total_qty": flt(item.qty),
			"packed_qty": packed_qty,
			"remaining_qty": remaining_qty,
			"uom": item.uom,
			"case_pack": cint(case_pack) if case_pack else None,
		})

	# Fetch customer transporter defaults if available (safe access)
	customer_defaults = {}
	if dn.customer and frappe.db.exists("Customer", dn.customer):
		cust_doc = frappe.get_cached_doc("Customer", dn.customer)
		customer_defaults = {
			"default_transporter": cust_doc.get("custom_default_transporter"),
			"default_from_address": cust_doc.get("custom_default_transporter_from_address"),
			"default_is_godown": cint(cust_doc.get("custom_is_godown_delivery")),
			"default_to_address": cust_doc.get("custom_default_transporter_to_address"),
		}

	return {
		"delivery_note": delivery_note,
		"customer": dn.customer,
		"customer_name": dn.customer_name,
		"docstatus": dn.docstatus,
		"current_transporter": {
			"transporter": dn.get("custom_transporter"),
			"from_address": dn.get("custom_transporter_from_address"),
			"from_address_display": dn.get("custom_transporter_from_address_display"),
			"is_godown_delivery": cint(dn.get("custom_is_godown_delivery")),
			"to_address": dn.get("custom_transporter_to_address"),
			"to_address_display": dn.get("custom_transporter_to_address_display"),
			"lr_no": dn.get("lr_no"),
			"lr_date": str(dn.get("lr_date")) if dn.get("lr_date") else None,
		},
		"customer_defaults": customer_defaults,
		"items": items_summary,
		"total_boxes_created": len(packing_slips),
		"next_package_no": max_case_no + 1 if max_case_no > 0 else 1,
	}


@frappe.whitelist()
def generate_packing_slips(delivery_note, packing_type="single", item_code=None, qty_per_box=0, no_of_boxes=1, mixed_items=None):
	"""
	Creates sequential Packing Slip documents for a Delivery Note.
	- packing_type == "single": Generates `no_of_boxes` containing `qty_per_box` of `item_code`.
	- packing_type == "mixed": Generates `no_of_boxes` each containing the items listed in `mixed_items`.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	no_of_boxes = cint(no_of_boxes)
	if no_of_boxes <= 0:
		frappe.throw(_("Number of boxes to generate must be at least 1"))

	dn = frappe.get_doc("Delivery Note", delivery_note)

	# Find highest existing package number
	existing_max = 0
	existing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": delivery_note, "docstatus": ["<", 2]},
		fields=["from_case_no", "to_case_no"],
	)
	for ps in existing_slips:
		existing_max = max(existing_max, cint(ps.to_case_no) or cint(ps.from_case_no) or 0)

	created_slips = []

	if packing_type == "single":
		if not item_code:
			frappe.throw(_("Item Code is required for single item packing"))
		qty_per_box = flt(qty_per_box)
		if qty_per_box <= 0:
			frappe.throw(_("Quantity per box must be greater than 0"))

		dn_item = next((i for i in dn.items if i.item_code == item_code), None)
		if not dn_item:
			frappe.throw(_("Item {0} not found in Delivery Note").format(item_code))

		for b in range(no_of_boxes):
			pkg_no = existing_max + b + 1
			ps = frappe.get_doc({
				"doctype": "Packing Slip",
				"delivery_note": delivery_note,
				"from_case_no": pkg_no,
				"to_case_no": pkg_no,
				"items": [
					{
						"item_code": item_code,
						"item_name": dn_item.item_name or item_code,
						"description": dn_item.description,
						"qty": qty_per_box,
						"stock_uom": dn_item.stock_uom or dn_item.uom,
						"dn_detail": dn_item.name,
					}
				]
			})
			ps.insert(ignore_permissions=True)
			created_slips.append(ps.name)

	elif packing_type == "mixed":
		if isinstance(mixed_items, str):
			mixed_items = json.loads(mixed_items)

		if not mixed_items or not isinstance(mixed_items, list):
			frappe.throw(_("Mixed items list is required for mixed carton packing"))

		items_to_add = []
		for mi in mixed_items:
			m_code = mi.get("item_code")
			m_qty = flt(mi.get("qty", 0))
			if m_qty > 0:
				dn_item = next((i for i in dn.items if i.item_code == m_code), None)
				if dn_item:
					items_to_add.append({
						"item_code": m_code,
						"item_name": dn_item.item_name or m_code,
						"description": dn_item.description,
						"qty": m_qty,
						"stock_uom": dn_item.stock_uom or dn_item.uom,
						"dn_detail": dn_item.name,
					})

		if not items_to_add:
			frappe.throw(_("At least one item with quantity > 0 is required for mixed carton"))

		for b in range(no_of_boxes):
			pkg_no = existing_max + b + 1
			ps = frappe.get_doc({
				"doctype": "Packing Slip",
				"delivery_note": delivery_note,
				"from_case_no": pkg_no,
				"to_case_no": pkg_no,
				"items": items_to_add
			})
			ps.insert(ignore_permissions=True)
			created_slips.append(ps.name)

	# Update total boxes on delivery note
	total_count = existing_max + len(created_slips)
	dn.db_set("custom_total_boxes", total_count, update_modified=True)
	frappe.db.commit()

	return {
		"message": _("Successfully generated {0} Packing Slip(s)").format(len(created_slips)),
		"created_packing_slips": created_slips,
		"total_boxes": total_count,
	}


@frappe.whitelist()
def get_packing_slips_list(delivery_note):
	"""
	Returns all Packing Slips for a Delivery Note with their box range and contents.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	packing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": delivery_note, "docstatus": ["<", 2]},
		fields=["name", "from_case_no", "to_case_no", "gross_weight_pkg", "net_weight_pkg", "creation"],
		order_by="from_case_no asc",
	)

	result = []
	for ps in packing_slips:
		items = frappe.get_all(
			"Packing Slip Item",
			filters={"parent": ps.name},
			fields=["item_code", "item_name", "qty", "stock_uom"],
		)
		result.append({
			"name": ps.name,
			"box_no": ps.from_case_no if ps.from_case_no == ps.to_case_no else f"{ps.from_case_no} - {ps.to_case_no}",
			"from_case_no": ps.from_case_no,
			"to_case_no": ps.to_case_no,
			"gross_weight": flt(ps.gross_weight_pkg),
			"net_weight": flt(ps.net_weight_pkg),
			"items": items,
			"items_display": ", ".join([f"{i.item_code} x {flt(i.qty):g} {i.stock_uom or ''}".strip() for i in items]),
			"creation": str(ps.creation),
		})

	return result


@frappe.whitelist()
def delete_packing_slips(delivery_note, packing_slip_names=None):
	"""
	Deletes selected Packing Slips (or all if packing_slip_names is empty) for a Delivery Note.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	if isinstance(packing_slip_names, str):
		packing_slip_names = json.loads(packing_slip_names)

	if packing_slip_names:
		filters = {"name": ["in", packing_slip_names], "delivery_note": delivery_note}
	else:
		filters = {"delivery_note": delivery_note}

	slips_to_delete = frappe.get_all("Packing Slip", filters=filters, fields=["name"])

	deleted_count = 0
	for s in slips_to_delete:
		frappe.delete_doc("Packing Slip", s.name, ignore_permissions=True)
		deleted_count += 1

	# Recalculate remaining boxes
	remaining_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": delivery_note, "docstatus": ["<", 2]},
		fields=["name"],
	)
	frappe.db.set_value("Delivery Note", delivery_note, "custom_total_boxes", len(remaining_slips), update_modified=True)
	frappe.db.commit()

	return {
		"message": _("Deleted {0} Packing Slip(s)").format(deleted_count),
		"deleted_count": deleted_count,
		"remaining_count": len(remaining_slips),
	}


@frappe.whitelist()
def get_bulk_packing_labels_html(delivery_note):
	"""
	Renders a continuous multi-page thermal print HTML string containing 4x6 labels
	for all Packing Slips of a Delivery Note in sequential order.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	packing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": delivery_note, "docstatus": ["<", 2]},
		fields=["name"],
		order_by="from_case_no asc",
	)

	if not packing_slips:
		frappe.throw(_("No Packing Slips found for Delivery Note {0}").format(delivery_note))

	html_pages = []
	for ps in packing_slips:
		# Use Carton Shipping Label (4x6) print format
		page_html = frappe.get_print("Packing Slip", ps.name, print_format="Carton Shipping Label (4x6)", no_letterhead=1)
		html_pages.append(page_html)

	# Combine pages with print page break separator
	combined_html = """
	<!DOCTYPE html>
	<html>
	<head>
		<meta charset="utf-8">
		<title>Bulk Carton Labels - {0}</title>
		<style>
			@page {{ size: 4in 6in; margin: 4mm 5mm; }}
			@media print {{
				.page-break {{ page-break-after: always; break-after: page; }}
			}}
		</style>
	</head>
	<body style="margin: 0; padding: 0;">
		{1}
	</body>
	</html>
	""".format(
		delivery_note,
		'<div class="page-break"></div>'.join(html_pages)
	)

	return combined_html
