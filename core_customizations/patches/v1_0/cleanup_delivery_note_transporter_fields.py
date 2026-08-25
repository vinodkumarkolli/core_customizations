import frappe

def execute():
	"""
	Remove deprecated Delivery Note and Customer custom transporter fields from the database.
	"""
	fields_to_remove = [
		"Delivery Note-custom_transporter_section",
		"Delivery Note-custom_transporter",
		"Customer-custom_transporter_section"
	]

	for fname in fields_to_remove:
		if frappe.db.exists("Custom Field", fname):
			frappe.delete_doc("Custom Field", fname, ignore_permissions=True)

	frappe.db.commit()
