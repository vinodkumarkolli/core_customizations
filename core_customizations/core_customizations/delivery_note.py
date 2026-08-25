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


def _get_item_case_pack(item_code):
	"""Returns the item's case pack qty if configured."""
	if not item_code:
		return None
	if frappe.db.has_column("Item", "custom_case_pack_qty"):
		qty = frappe.db.get_value("Item", item_code, "custom_case_pack_qty")
		return cint(qty) if qty else None
	return None



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
	transporter_supplier_name = (
		frappe.db.get_value("Supplier", transporter, "supplier_name") if transporter else None
	)

	update_dict = {
		"transporter": transporter or None,
		"transporter_name": transporter_supplier_name,
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
		"transporter_name": transporter_supplier_name,
		"from_address": from_address,
		"from_address_display": from_address_display,
		"is_godown_delivery": is_godown,
		"to_address": to_address if is_godown else None,
		"to_address_display": to_address_display if is_godown else "",
		"lr_no": lr_no,
		"lr_date": str(lr_date) if lr_date else None,
	}



@frappe.whitelist()
def get_lr_dialog_info(delivery_note):
	"""
	Returns linked Sales Invoices, current LR details, and E-Way Bill status
	for the interactive Delivery Note LR Details popup.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	dn = frappe.get_doc("Delivery Note", delivery_note)

	# Find linked Sales Invoices (non-cancelled)
	linked_si_names = frappe.get_all(
		"Sales Invoice Item",
		filters={"delivery_note": delivery_note, "docstatus": ["!=", 2]},
		distinct=True,
		pluck="parent"
	)

	sales_invoices = []
	active_ewaybill = dn.get("ewaybill")
	max_invoice_val = flt(dn.grand_total)

	for si_name in linked_si_names:
		si = frappe.get_doc("Sales Invoice", si_name)
		if si.get("ewaybill") and not active_ewaybill:
			active_ewaybill = si.get("ewaybill")
		if flt(si.grand_total) > max_invoice_val:
			max_invoice_val = flt(si.grand_total)
		sales_invoices.append({
			"name": si.name,
			"grand_total": si.grand_total,
			"rounded_total": si.rounded_total,
			"ewaybill": si.get("ewaybill"),
			"docstatus": si.docstatus,
		})

	return {
		"has_sales_invoice": len(sales_invoices) > 0,
		"sales_invoices": sales_invoices,
		"current_lr": {
			"lr_no": dn.lr_no or "",
			"lr_date": str(dn.lr_date) if dn.lr_date else "",
			"vehicle_no": dn.vehicle_no or "",
			"mode_of_transport": dn.get("mode_of_transport") or "Road",
			"gst_vehicle_type": dn.get("gst_vehicle_type") or "Regular",
			"lr_receipt_image": dn.get("custom_lr_receipt_image") or "",
			"ewaybill": active_ewaybill,
		},
		"max_invoice_value": max_invoice_val,
		"is_above_threshold": max_invoice_val > 50000.0,
		"ewaybill_no": active_ewaybill,
	}


@frappe.whitelist()
def update_lr_details(
	delivery_note,
	lr_no=None,
	lr_date=None,
	vehicle_no=None,
	mode_of_transport="Road",
	gst_vehicle_type="Regular",
	lr_receipt_image=None,
	auto_update_ewaybill=1,
):
	"""
	Whitelisted method to update Lorry Receipt (LR) number, date, vehicle number,
	transport mode, and LR receipt photo on a Delivery Note and all linked Sales Invoices.
	Optionally triggers E-Way Bill Part B update via india_compliance if an active EWB is present.
	
	Business Purpose: Sync logistics details ([BR-LOG-002]) and enforce Consignor Part B Authority ([BR-EWB-003]).
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	dn = frappe.get_doc("Delivery Note", delivery_note)
	formatted_vehicle_no = (vehicle_no or "").replace(" ", "").upper() or None
	parsed_lr_date = getdate(lr_date) if lr_date else None

	# 1. Update Delivery Note
	dn.db_set({
		"lr_no": lr_no or None,
		"lr_date": parsed_lr_date,
		"vehicle_no": formatted_vehicle_no,
		"mode_of_transport": mode_of_transport or "Road",
		"gst_vehicle_type": gst_vehicle_type or "Regular",
		"custom_lr_receipt_image": lr_receipt_image or None,
	}, update_modified=True)

	# @businessRule [BR-LOG-002] Sync LR Details
	# 2. Synchronize to all linked Sales Invoices
	linked_si_names = frappe.get_all(
		"Sales Invoice Item",
		filters={"delivery_note": delivery_note, "docstatus": ["!=", 2]},
		distinct=True,
		pluck="parent"
	)


	target_ewb_doc = None
	if dn.get("ewaybill"):
		target_ewb_doc = dn

	for si_name in linked_si_names:
		si = frappe.get_doc("Sales Invoice", si_name)
		si.db_set({
			"lr_no": lr_no or None,
			"lr_date": parsed_lr_date,
			"vehicle_no": formatted_vehicle_no,
			"mode_of_transport": mode_of_transport or "Road",
			"gst_vehicle_type": gst_vehicle_type or "Regular",
			"custom_lr_receipt_image": lr_receipt_image or None,
		}, update_modified=True)
		if si.get("ewaybill") and not target_ewb_doc:
			target_ewb_doc = si

	frappe.db.commit()

	# 3. E-Way Bill Part B Auto-Update via india_compliance
	ewb_status = None
	if formatted_vehicle_no and cint(auto_update_ewaybill) and target_ewb_doc and target_ewb_doc.get("ewaybill"):
		try:
			from india_compliance.gst_india.utils.e_waybill import update_vehicle_info

			ewb_values = {
				"vehicle_no": formatted_vehicle_no,
				"lr_no": lr_no or "",
				"lr_date": str(parsed_lr_date) if parsed_lr_date else "",
				"mode_of_transport": mode_of_transport or "Road",
				"gst_vehicle_type": gst_vehicle_type or "Regular",
				"reason_code": "1",  # Transshipment / Line-haul dispatch
				"reason_remark": "Updated from Delivery Note LR Booking",
				"update_e_waybill_data": 1,
			}
			update_vehicle_info(doctype=target_ewb_doc.doctype, docname=target_ewb_doc.name, values=ewb_values)
			ewb_status = {
				"success": True,
				"message": _("E-Way Bill Part B updated successfully on GST Portal for {0}").format(target_ewb_doc.get("ewaybill")),
			}
		except Exception as e:
			frappe.log_error(f"E-Waybill Part B update failed for {target_ewb_doc.name}: {e}", "Core Customizations E-Waybill")
			ewb_status = {
				"success": False,
				"error": str(e),
			}

	return {
		"message": _("LR Details updated successfully"),
		"lr_no": lr_no,
		"lr_date": str(parsed_lr_date) if parsed_lr_date else None,
		"vehicle_no": formatted_vehicle_no,
		"lr_receipt_image": lr_receipt_image,
		"synced_invoices": linked_si_names,
		"ewb_status": ewb_status,
	}


def auto_populate_shipping_contact_details(doc):
	"""
	Auto-populates shipping contact person and details if empty,
	falling back to billing contact_person or customer's primary contact.
	"""
	if not doc.get("customer"):
		return

	# 1. Billing Contact Person fallback if empty
	if not doc.get("contact_person"):
		primary_contact = frappe.db.get_value("Customer", doc.customer, "customer_primary_contact")
		if not primary_contact:
			primary_contact = frappe.db.get_value(
				"Dynamic Link",
				{"link_doctype": "Customer", "link_name": doc.customer, "parenttype": "Contact"},
				"parent"
			)
		if primary_contact:
			doc.contact_person = primary_contact

	# Sync billing contact details if contact_person is present
	if doc.get("contact_person") and (not doc.get("contact_mobile") or not doc.get("contact_display")):
		c_doc = frappe.get_doc("Contact", doc.contact_person)
		if not doc.get("contact_display"):
			doc.contact_display = c_doc.full_name or c_doc.name
		if not doc.get("contact_mobile"):
			doc.contact_mobile = c_doc.mobile_no or c_doc.phone
		if not doc.get("contact_email"):
			doc.contact_email = c_doc.email_id

	# 2. Shipping Contact Person fallback if empty
	if not doc.get("shipping_contact_person"):
		shipping_contact = None
		if doc.get("shipping_address_name"):
			shipping_contact = frappe.db.get_value(
				"Dynamic Link",
				{"link_doctype": "Address", "link_name": doc.shipping_address_name, "parenttype": "Contact"},
				"parent"
			)
		if not shipping_contact:
			shipping_contact = doc.get("contact_person") or frappe.db.get_value("Customer", doc.customer, "customer_primary_contact")
		if not shipping_contact:
			shipping_contact = frappe.db.get_value(
				"Dynamic Link",
				{"link_doctype": "Customer", "link_name": doc.customer, "parenttype": "Contact"},
				"parent"
			)

		if shipping_contact:
			doc.shipping_contact_person = shipping_contact

	# Sync shipping contact details if shipping_contact_person is present
	if doc.get("shipping_contact_person"):
		sc_doc = frappe.get_doc("Contact", doc.shipping_contact_person)
		if not doc.get("shipping_contact_display"):
			doc.shipping_contact_display = sc_doc.full_name or sc_doc.name
		if not doc.get("shipping_contact_mobile"):
			doc.shipping_contact_mobile = sc_doc.mobile_no or sc_doc.phone
		if not doc.get("shipping_contact_email"):
			doc.shipping_contact_email = sc_doc.email_id


def validate_delivery_note(doc, method=None):
	"""
	Ensures transporter name is populated from Supplier,
	ensures address display fields are populated and sanitized,
	ensures shipping and billing contact details are auto-populated,
	and clears destination address if Godown Delivery is disabled.
	
	Business Purpose: Enforce data consistency and Single Warehouse Confinement ([BR-INV-001]).
	"""
	# 1. Auto-populate shipping and billing contact details
	auto_populate_shipping_contact_details(doc)

	# 2. Sync standard transporter_name if transporter is set
	if doc.get("transporter") and not doc.get("transporter_name"):
		doc.transporter_name = frappe.db.get_value("Supplier", doc.transporter, "supplier_name") or doc.transporter

	# 3. If is_godown_delivery is 0, ensure destination address is cleared
	if not doc.get("custom_is_godown_delivery"):
		doc.custom_transporter_to_address = None
		doc.custom_transporter_to_address_display = ""

	# 4. Auto-populate sanitized address display fields
	if doc.get("custom_transporter_from_address"):
		doc.custom_transporter_from_address_display = _get_formatted_address(doc.custom_transporter_from_address)
	else:
		doc.custom_transporter_from_address_display = ""

	if doc.get("custom_is_godown_delivery") and doc.get("custom_transporter_to_address"):
		doc.custom_transporter_to_address_display = _get_formatted_address(doc.custom_transporter_to_address)
	else:
		doc.custom_transporter_to_address_display = ""

	# @businessRule [BR-INV-001] Single Warehouse Confinement
	# 5. Enforce Single Warehouse confinement across all Item rows
	primary_warehouse = None
	for item in doc.get("items", []):
		if item.get("warehouse"):
			if not primary_warehouse:
				primary_warehouse = item.warehouse
			elif item.warehouse != primary_warehouse:
				frappe.throw(
					_("A Delivery Note should be confined to a single warehouse only ({0}). Row #{1} ({2}) has warehouse '{3}'. Please select '{0}' or create a separate Delivery Note for other warehouses.").format(
						primary_warehouse, item.idx, item.item_code or item.item_name or "", item.warehouse
					),
					title=_("Multiple Warehouses Not Allowed")
				)




def before_submit_delivery_note(doc, method=None):
	"""
	Automatically submits all linked Draft Packing Slips before the Delivery Note is submitted.
	
	Business Purpose: Enforce Bulk Submission Synchronization ([BR-PAC-002]).
	"""
	draft_packing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": doc.name, "docstatus": 0},
		fields=["name"],
	)
	for ps in draft_packing_slips:
		ps_doc = frappe.get_doc("Packing Slip", ps.name)
		ps_doc.submit()


def on_cancel_delivery_note(doc, method=None):
	"""
	Automatically cancels all linked Submitted Packing Slips when the Delivery Note is cancelled.
	
	Business Purpose: Maintain Document Dependency Guardrails ([BR-PAC-002], [BR-CAN-001]).
	"""
	submitted_packing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": doc.name, "docstatus": 1},
		fields=["name"],
	)
	for ps in submitted_packing_slips:
		ps_doc = frappe.get_doc("Packing Slip", ps.name)
		ps_doc.cancel()


@frappe.whitelist()
def get_unpacked_items_summary(delivery_note):
	"""
	Returns a summary of items in the Delivery Note with:
	- standard qty
	- packed qty (sum of all active packing slips)
	- remaining unpacked balance
	- item case pack (if configured)
	- current transporter details
	- customer master default transporter settings
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note is required"))

	dn = frappe.get_doc("Delivery Note", delivery_note)

	# Get all active packing slips (draft or submitted)
	packing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": delivery_note, "docstatus": ["<", 2]},
		fields=["name", "from_case_no", "to_case_no"],
		order_by="from_case_no asc",
	)

	# Calculate packed quantities per Delivery Note Item row (using dn_detail)
	packed_qty_map = {}
	max_case_no = 0
	
	if packing_slips:
		ps_names = [ps.name for ps in packing_slips]
		ps_items = frappe.get_all(
			"Packing Slip Item",
			filters={"parent": ["in", ps_names]},
			fields=["dn_detail", "qty"]
		)
		
		for ps in packing_slips:
			to_case = cint(ps.to_case_no) or cint(ps.from_case_no) or 1
			if to_case > max_case_no:
				max_case_no = to_case
				
		for item in ps_items:
			if item.dn_detail:
				packed_qty_map[item.dn_detail] = packed_qty_map.get(item.dn_detail, 0) + flt(item.qty)

	# Build items summary
	items_summary = []
	for item in dn.items:
		packed_qty = packed_qty_map.get(item.name, 0)
		remaining_qty = max(0, flt(item.qty) - packed_qty)
		case_pack = _get_item_case_pack(item.item_code)

		items_summary.append({
			"dn_detail": item.name,
			"item_code": item.item_code,
			"item_name": item.item_name,
			"qty": flt(item.qty),
			"packed_qty": packed_qty,
			"remaining_qty": remaining_qty,
			"uom": item.uom,
			"case_pack": case_pack,
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
			"transporter": dn.get("transporter") or dn.get("custom_transporter"),
			"transporter_name": dn.get("transporter_name"),
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
	
	Business Purpose: Supports Draft Carton Packing Slips generation ([BR-PAC-001]).
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
	Returns all Packing Slips for a Delivery Note with their box range, contents, and submission status.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	packing_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": delivery_note, "docstatus": ["<", 2]},
		fields=["name", "from_case_no", "to_case_no", "gross_weight_pkg", "net_weight_pkg", "creation", "docstatus"],
		order_by="from_case_no asc",
	)

	result = []
	for ps in packing_slips:
		items = frappe.get_all(
			"Packing Slip Item",
			filters={"parent": ps.name},
			fields=["item_code", "item_name", "qty", "stock_uom"],
		)
		status_label = "Draft" if ps.docstatus == 0 else ("Submitted" if ps.docstatus == 1 else "Cancelled")
		result.append({
			"name": ps.name,
			"box_no": ps.from_case_no if ps.from_case_no == ps.to_case_no else f"{ps.from_case_no} - {ps.to_case_no}",
			"from_case_no": ps.from_case_no,
			"to_case_no": ps.to_case_no,
			"gross_weight": flt(ps.gross_weight_pkg),
			"net_weight": flt(ps.net_weight_pkg),
			"docstatus": ps.docstatus,
			"status": status_label,
			"items": items,
			"items_display": ", ".join([f"{i.item_code} x {flt(i.qty):g} {i.stock_uom or ''}".strip() for i in items]),
			"creation": str(ps.creation),
		})

	return result


@frappe.whitelist()
def submit_packing_slips(delivery_note, packing_slip_names=None):
	"""
	Submits selected draft Packing Slips (or all draft slips if packing_slip_names is empty)
	linked to a Delivery Note.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	if isinstance(packing_slip_names, str):
		packing_slip_names = json.loads(packing_slip_names)

	filters = {"delivery_note": delivery_note, "docstatus": 0}
	if packing_slip_names:
		filters["name"] = ["in", packing_slip_names]

	slips_to_submit = frappe.get_all("Packing Slip", filters=filters, pluck="name", order_by="from_case_no asc")

	submitted_count = 0
	for ps_name in slips_to_submit:
		ps = frappe.get_doc("Packing Slip", ps_name)
		ps.flags.ignore_permissions = True
		ps.submit()
		submitted_count += 1

	frappe.db.commit()

	return {
		"message": _("Successfully submitted {0} Packing Slip(s)").format(submitted_count),
		"submitted_count": submitted_count,
		"submitted_slips": slips_to_submit,
	}



@frappe.whitelist()
def cancel_packing_slips(delivery_note, packing_slip_names=None):
	"""
	Cancels selected Submitted Packing Slips for a Delivery Note.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	if isinstance(packing_slip_names, str):
		packing_slip_names = json.loads(packing_slip_names)

	if packing_slip_names:
		filters = {"name": ["in", packing_slip_names], "delivery_note": delivery_note, "docstatus": 1}
	else:
		filters = {"delivery_note": delivery_note, "docstatus": 1}

	slips_to_cancel = frappe.get_all("Packing Slip", filters=filters, fields=["name"])

	cancelled_count = 0
	for s in slips_to_cancel:
		doc = frappe.get_doc("Packing Slip", s.name)
		doc.cancel()
		cancelled_count += 1

	return {
		"message": _("{0} Packing Slip(s) cancelled successfully").format(cancelled_count),
		"cancelled_count": cancelled_count
	}

@frappe.whitelist()
def delete_packing_slips(delivery_note, packing_slip_names=None):
	"""
	Deletes selected Packing Slips (or all if packing_slip_names is empty) for a Delivery Note.
	Skips Submitted Packing Slips and reports them.
	"""
	if not delivery_note:
		frappe.throw(_("Delivery Note name is required"))

	if isinstance(packing_slip_names, str):
		packing_slip_names = json.loads(packing_slip_names)

	if packing_slip_names:
		filters = {"name": ["in", packing_slip_names], "delivery_note": delivery_note}
	else:
		filters = {"delivery_note": delivery_note}

	slips_to_delete = frappe.get_all("Packing Slip", filters=filters, fields=["name", "docstatus"])

	deleted_count = 0
	failed_slips = []
	for s in slips_to_delete:
		if s.docstatus == 1:
			failed_slips.append(s.name)
		else:
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

	if failed_slips:
		if deleted_count > 0:
			msg = _("{0} Draft/Cancelled Packing Slip(s) deleted. {1} Submitted Packing Slip(s) ({2}) cannot be deleted and must be Cancelled first.").format(
				deleted_count, len(failed_slips), ", ".join(failed_slips)
			)
		else:
			msg = _("{0} Submitted Packing Slip(s) ({1}) cannot be deleted and must be Cancelled first.").format(
				len(failed_slips), ", ".join(failed_slips)
			)
		frappe.msgprint(msg, title=_("Partial Deletion"), indicator="orange")
		return {
			"message": msg,
			"deleted_count": deleted_count,
			"remaining_count": len(remaining_slips),
			"partial": True
		}
	else:
		return {
			"message": _("Deleted {0} Packing Slip(s)").format(deleted_count),
			"deleted_count": deleted_count,
			"remaining_count": len(remaining_slips),
			"partial": False
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
		filters={"delivery_note": delivery_note, "docstatus": 1},
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
