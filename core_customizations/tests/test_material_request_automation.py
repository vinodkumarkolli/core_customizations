import frappe
import unittest

class TestMaterialRequestAutomation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.flags.ignore_permissions = True
		cls.company = "Sravi Enterprises - Kolapakkam"
		if not frappe.db.exists("Company", cls.company):
			# fallback to any company if tests are running elsewhere
			cls.company = frappe.db.get_value("Company")

		# Ensure a supplier exists
		cls.supplier_name = "_Test Auto PO Supplier"
		if not frappe.db.exists("Supplier", {"supplier_name": cls.supplier_name}):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": cls.supplier_name,
				"supplier_group": "Services"
			}).insert(ignore_permissions=True)
		cls.supplier = frappe.db.get_value("Supplier", {"supplier_name": cls.supplier_name}, "name")

		# Ensure an item exists
		cls.item_code = "_Test Auto PO Item"
		if not frappe.db.exists("Item", cls.item_code):
			# Ensure HSN Code exists
			if not frappe.db.exists("GST HSN Code", "999999"):
				frappe.get_doc({
					"doctype": "GST HSN Code",
					"hsn_code": "999999",
					"description": "Test HSN Code"
				}).insert(ignore_permissions=True)
				
			frappe.get_doc({
				"doctype": "Item",
				"item_code": cls.item_code,
				"item_name": cls.item_code,
				"item_group": "Products",
				"is_stock_item": 1,
				"stock_uom": "Nos",
				"gst_hsn_code": "999999",
				"uoms": [{"uom": "Nos", "conversion_factor": 1.0}],
			}).insert(ignore_permissions=True)
		
		cls.item = frappe.db.get_value("Item", cls.item_code, "name")

		# Always ensure the Item Supplier row exists (idempotent)
		# Supplier is configured in the "Item Supplier" child table (Purchasing tab)
		if not frappe.db.exists("Item Supplier", {"parent": cls.item_code, "supplier": cls.supplier}):
			item_doc = frappe.get_doc("Item", cls.item_code)
			item_doc.append("supplier_items", {"supplier": cls.supplier})
			item_doc.save(ignore_permissions=True)

		# Ensure a warehouse exists
		cls.warehouse_name = f"_Test Auto PO Warehouse - {frappe.db.get_value('Company', cls.company, 'abbr')}"
		if not frappe.db.exists("Warehouse", cls.warehouse_name):
			frappe.get_doc({
				"doctype": "Warehouse",
				"warehouse_name": "_Test Auto PO Warehouse",
				"company": cls.company
			}).insert(ignore_permissions=True)
		cls.warehouse = cls.warehouse_name

	def test_01_auto_po_created_on_mr_submit(self):
		"""Verify that submitting a Material Request of type Purchase auto-generates a Draft PO."""
		# Create a Material Request
		mr = frappe.get_doc({
			"doctype": "Material Request",
			"material_request_type": "Purchase",
			"company": self.company,
			"transaction_date": frappe.utils.today(),
			"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
			"set_warehouse": self.warehouse,
			"items": [{
				"item_code": self.item,
				"qty": 10,
				"uom": "Nos",
				"warehouse": self.warehouse,
				"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
			}]
		}).insert(ignore_permissions=True)
		
		# Submit MR
		mr.submit()
		
		# Check if PO was created
		po_item = frappe.db.get_value("Purchase Order Item", {"material_request": mr.name, "item_code": self.item}, ["parent", "qty"], as_dict=True)
		self.assertTrue(po_item, "Purchase Order was not automatically created from Material Request.")
		
		# Validate PO details
		po = frappe.get_doc("Purchase Order", po_item.parent)
		self.assertEqual(po.docstatus, 0, "Generated PO should be in Draft state.")
		self.assertEqual(po.supplier, self.supplier, "Generated PO has incorrect supplier.")
		self.assertEqual(po.set_warehouse, self.warehouse, "Generated PO did not inherit set_warehouse from MR.")
		self.assertEqual(po_item.qty, 10, "Generated PO item quantity mismatch.")
		
	def test_02_idempotency_prevents_duplicate_pos(self):
		"""Verify that re-triggering the hook does not create duplicate POs."""
		mr = frappe.get_doc({
			"doctype": "Material Request",
			"material_request_type": "Purchase",
			"company": self.company,
			"transaction_date": frappe.utils.today(),
			"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
			"set_warehouse": self.warehouse,
			"items": [{
				"item_code": self.item,
				"qty": 5,
				"uom": "Nos",
				"warehouse": self.warehouse,
				"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
			}]
		}).insert(ignore_permissions=True)
		
		mr.submit()
		
		# Count POs
		initial_po_count = frappe.db.count("Purchase Order Item", {"material_request": mr.name})
		self.assertEqual(initial_po_count, 1)
		
		# Manually trigger hook again
		from core_customizations.core_customizations.material_request import auto_create_po
		auto_create_po(mr, "on_submit")
		
		# Count POs again
		final_po_count = frappe.db.count("Purchase Order Item", {"material_request": mr.name})
		self.assertEqual(final_po_count, 1, "Duplicate PO was generated for the same MR.")

	def test_03_single_supplier_constraint_blocks_automation(self):
		"""
		[BR-PROC-003] Verify MR→PO automation is blocked when an item has
		zero or more than one supplier configured in Item Supplier table.
		"""
		from core_customizations.core_customizations.material_request import auto_create_po

		# Create a second supplier for the item, giving it 2 suppliers
		second_supplier_name = "_Test Auto PO Supplier 2"
		if not frappe.db.exists("Supplier", {"supplier_name": second_supplier_name}):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": second_supplier_name,
				"supplier_group": "Services"
			}).insert(ignore_permissions=True)
		second_supplier = frappe.db.get_value("Supplier", {"supplier_name": second_supplier_name}, "name")

		# Add second supplier row to item — now item has 2 suppliers
		if not frappe.db.exists("Item Supplier", {"parent": self.item_code, "supplier": second_supplier}):
			item_doc = frappe.get_doc("Item", self.item_code)
			item_doc.append("supplier_items", {"supplier": second_supplier})
			item_doc.save(ignore_permissions=True)

		try:
			mr = frappe.get_doc({
				"doctype": "Material Request",
				"material_request_type": "Purchase",
				"company": self.company,
				"transaction_date": frappe.utils.today(),
				"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
				"set_warehouse": self.warehouse,
				"items": [{
					"item_code": self.item,
					"qty": 3,
					"uom": "Nos",
					"warehouse": self.warehouse,
					"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
				}]
			}).insert(ignore_permissions=True)
			mr.submit()

			# Automation should have aborted — no PO should exist
			po_count = frappe.db.count("Purchase Order Item", {"material_request": mr.name})
			self.assertEqual(
				po_count, 0,
				"[BR-PROC-003] PO was auto-created despite item having multiple suppliers — single-supplier constraint violated."
			)
		finally:
			# Cleanup: remove the second supplier row so other tests are unaffected
			frappe.db.delete("Item Supplier", {"parent": self.item_code, "supplier": second_supplier})
			frappe.db.commit()
