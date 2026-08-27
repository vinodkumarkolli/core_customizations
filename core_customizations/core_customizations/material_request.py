import re

import frappe


def auto_create_po(doc, method):
	"""Create draft Purchase Orders from a Purchase Material Request."""
	if doc.material_request_type != "Purchase":
		return

	frappe.log_error("auto_create_po triggered for " + doc.name)
	groups = build_po_groups(doc)
	if not groups:
		frappe.log_error(title=f"MR→PO Automation Skipped: {doc.name}", message="No valid warehouse/supplier groups found.")
		return

	for group in groups:
		if existing_purchase_order_for_group(doc.name, group["warehouse"], group["supplier"]):
			frappe.log_error(
				title=f"MR→PO Automation Skipped: {doc.name}",
				message=(
					f"Purchase Order already exists for MR {doc.name}, warehouse {group['warehouse']}, "
					f"and supplier {group['supplier']}."
				),
			)
			continue

		try:
			po = make_purchase_order(doc.name)
			po.supplier = group["supplier"]
			if group["warehouse"]:
				po.set_warehouse = group["warehouse"]

			po.items = [item for item in po.items if item.material_request == doc.name and item.warehouse == group["warehouse"] and item.item_code in group["item_codes"]]
			if not po.items:
				continue

			po.set_missing_values()
			po.insert(ignore_permissions=True)
			send_po_email(po)
		except Exception:
			frappe.log_error(title=f"Failed to auto-create PO for {doc.name}", message=frappe.get_traceback())


def build_po_groups(doc):
	groups = {}
	for item in doc.items:
		supplier = get_single_supplier(item.item_code)
		if not supplier:
			frappe.log_error(
				title=f"MR→PO Automation Skipped: {doc.name}",
				message=(
					f"Item '{item.item_code}' has zero or multiple suppliers configured. "
					"Automation requires exactly 1 supplier per item."
				),
			)
			return []

		warehouse = resolve_target_warehouse(doc, item)
		if not warehouse:
			frappe.log_error(
				title=f"MR→PO Automation Skipped: {doc.name}",
				message=(
					f"Item '{item.item_code}' does not resolve to a warehouse. "
					"Automation requires a warehouse to split Purchase Orders."
				),
			)
			return []

		key = (warehouse, supplier)
		if key not in groups:
			groups[key] = {
				"warehouse": warehouse,
				"supplier": supplier,
				"item_codes": set(),
			}
		groups[key]["item_codes"].add(item.item_code)

	return list(groups.values())


def resolve_target_warehouse(doc, item):
	if item.warehouse:
		return item.warehouse
	if doc.set_warehouse:
		return doc.set_warehouse
	return frappe.db.get_value("Item Reorder", {"parent": item.item_code}, "warehouse")


def get_single_supplier(item_code):
	item_suppliers = frappe.db.get_all("Item Supplier", filters={"parent": item_code}, fields=["supplier"])
	if len(item_suppliers) != 1:
		return None
	return item_suppliers[0].supplier


def existing_purchase_order_for_group(mr_name, warehouse, supplier):
	po_items = frappe.get_all(
		"Purchase Order Item",
		filters={"material_request": mr_name, "warehouse": warehouse},
		fields=["parent"],
		distinct=True,
	)
	for row in po_items:
		if frappe.db.get_value("Purchase Order", row.parent, "supplier") == supplier:
			return row.parent
	return None


def make_purchase_order(mr_name):
	try:
		from erpnext.stock.doctype.material_request.material_request import make_purchase_order
	except ImportError:
		from erpnext.stock.doctype.material_request.mapper import make_purchase_order
	return make_purchase_order(mr_name)


def send_po_email(po):
	recipients = []
	supplier_contact = frappe.db.get_value(
		"Dynamic Link",
		{"link_doctype": "Supplier", "link_name": po.supplier, "parenttype": "Contact"},
		"parent",
	)
	if supplier_contact:
		supplier_email = frappe.db.get_value("Contact", supplier_contact, "email_id")
		if supplier_email:
			recipients.append(supplier_email)

	company_email = frappe.db.get_value("Company", po.company, "email")
	if company_email:
		recipients.append(company_email)

	if not recipients:
		system_managers = frappe.get_all("Has Role", filters={"role": "System Manager", "parenttype": "User"}, fields=["parent"])
		if system_managers:
			recipients.append(system_managers[0].parent)

	attachments = []
	try:
		attachments.append(build_po_pdf_attachment(po))
	except Exception:
		frappe.log_error(title=f"Failed to build PO PDF attachment for {po.name}", message=frappe.get_traceback())

	frappe.sendmail(
		recipients=list(set(recipients)),
		subject=f"New Purchase Order Created: {po.name}",
		message=f"""
		<p>Hello,</p>
		<p>A new Purchase Order <b>{po.name}</b> has been automatically generated for <b>{po.supplier}</b>.</p>
		<p>Please log in to the system to review and approve the draft.</p>
		<p>Thank you.</p>
		""",
		reference_doctype="Purchase Order",
		reference_name=po.name,
		attachments=attachments,
	)


def build_po_pdf_attachment(po):
	from frappe.utils.print_utils import attach_print

	password = get_supplier_gstin(po.supplier)
	if not password:
		password = build_supplier_fallback_password(po.supplier)

	return attach_print(
		doctype="Purchase Order",
		name=po.name,
		file_name=f"{po.name}.pdf",
		print_format="GST Purchase Order",
		doc=po,
		password=password,
	)


def get_supplier_gstin(supplier):
	if not supplier:
		return None
	supplier_doc = frappe.get_cached_doc("Supplier", supplier)
	return (supplier_doc.get("tax_id") or supplier_doc.get("gstin") or "").strip() or None


def build_supplier_fallback_password(supplier):
	if not supplier:
		return None
	supplier_doc = frappe.get_cached_doc("Supplier", supplier)
	letters_only = re.sub(r"[^A-Za-z]", "", supplier_doc.supplier_name or supplier_doc.name or supplier)
	base = letters_only[:8].upper()
	if not base:
		return None
	if len(base) < 8:
		base += "".join(str(i) for i in range(1, 9))[: 8 - len(base)]
	return base
