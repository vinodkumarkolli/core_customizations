import frappe
from erpnext.stock.doctype.material_request.mapper import make_purchase_order

def auto_create_po(doc, method):
	"""
	Intercepts the Material Request submission event to automatically generate a Purchase Order.
	
	Business Purpose: Streamlines the procurement process by eliminating manual PO creation 
	when the system Auto Reorder logic raises a Material Request.
	
	Args:
		doc (Document): The Material Request document being submitted.
		method (str): The hook method name (e.g., 'on_submit').
		
	Raises:
		Exception: Logs to Frappe Error Log if PO creation or email dispatch fails.
	"""
	if doc.material_request_type != "Purchase":
		return

	frappe.log_error("auto_create_po triggered for " + doc.name)
	# @businessRule [BR-PROC-001] Automated PO Idempotency Check
	# Ensures that if a Material Request is re-submitted or modified, duplicate POs are not created.
	existing_po = frappe.db.get_value("Purchase Order Item", {"material_request": doc.name}, "parent")
	if existing_po:
		frappe.log_error("Existing PO found")
		return

	# @businessFormula Collect all unique default suppliers from the requested items
	suppliers = set()
	for item in doc.items:
		supplier = getattr(item, "default_supplier", None)
		if not supplier:
			supplier = frappe.db.get_value("Item Default", {"parent": item.item_code, "company": doc.company}, "default_supplier")
		if supplier:
			suppliers.add(supplier)

	frappe.log_error("Suppliers found: " + str(suppliers))
	if not suppliers:
		frappe.log_error("No suppliers found, aborting PO creation")
		return

	for supplier in suppliers:
		try:
			# Native ERPNext mapper to build the PO
			po = make_purchase_order(doc.name)
			po.supplier = supplier
			if doc.set_warehouse:
				po.set_warehouse = doc.set_warehouse
			
			# Filter items for this specific supplier only if there are multiple suppliers
			if len(suppliers) > 1:
				valid_items = []
				for po_item in po.items:
					mr_item = frappe.get_doc("Material Request Item", po_item.material_request_item)
					item_supplier = getattr(mr_item, "default_supplier", None)
					if not item_supplier:
						item_supplier = frappe.db.get_value("Item Default", {"parent": mr_item.item_code, "company": doc.company}, "default_supplier")
					
					if item_supplier == supplier:
						valid_items.append(po_item)
				
				po.items = valid_items
				
			if not po.items:
				continue

			# Set standard defaults like taxes, pricing, etc.
			po.set_missing_values()
			
			# @businessRule [BR-PROC-002] Draft PO Generation
			# All auto-generated POs must remain in Draft state for human review prior to submission.
			po.insert(ignore_permissions=True)
			
			# Dispatch Emails
			send_po_email(po)
			
		except Exception as e:
			frappe.log_error(title=f"Failed to auto-create PO for {doc.name}", message=frappe.get_traceback())

def send_po_email(po):
	"""
	Dispatches an email notification to both the Supplier and the internal purchasing team.
	
	Business Purpose: Ensures all stakeholders are immediately aware of newly auto-generated POs.
	
	Args:
		po (Document): The newly created Purchase Order document.
	"""
	recipients = []
	
	# 1. Supplier Email
	supplier_contact = frappe.db.get_value("Dynamic Link", {"link_doctype": "Supplier", "link_name": po.supplier, "parenttype": "Contact"}, "parent")
	if supplier_contact:
		supplier_email = frappe.db.get_value("Contact", supplier_contact, "email_id")
		if supplier_email:
			recipients.append(supplier_email)
	
	# 2. Internal Purchasing Email
	# Send to the company's default email or a specific purchase email if available
	company_email = frappe.db.get_value("Company", po.company, "email")
	if company_email:
		recipients.append(company_email)
	
	if not recipients:
		# Fallback to system manager if no emails found
		system_managers = frappe.get_all("Has Role", filters={"role": "System Manager", "parenttype": "User"}, fields=["parent"])
		if system_managers:
			recipients.append(system_managers[0].parent)

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
		reference_name=po.name
	)
