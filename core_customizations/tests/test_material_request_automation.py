import frappe
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core_customizations.core_customizations import material_request
from core_customizations.core_customizations.material_request import auto_create_po


class TestMaterialRequestAutomation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.flags.ignore_permissions = True
		cls.company = "Sravi Enterprises - Kolapakkam"
		if not frappe.db.exists("Company", cls.company):
			cls.company = frappe.db.get_value("Company")

		cls.supplier_name = "_Test Auto PO Supplier"
		cls.supplier = cls._ensure_supplier(cls.supplier_name)
		cls.second_supplier = cls._ensure_supplier("_Test Auto PO Supplier 2")

		cls.item_code = "_Test Auto PO Item"
		cls.item = cls._ensure_item(cls.item_code, cls.supplier)

		cls.secondary_item_code = "_Test Auto PO Item 2"
		cls.secondary_item = cls._ensure_item(cls.secondary_item_code, cls.second_supplier)

		cls.warehouse_name = f"_Test Auto PO Warehouse - {frappe.db.get_value('Company', cls.company, 'abbr')}"
		if not frappe.db.exists("Warehouse", cls.warehouse_name):
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "_Test Auto PO Warehouse",
					"company": cls.company,
				}
			).insert(ignore_permissions=True)
		cls.warehouse = cls.warehouse_name
		cls._ensure_warehouse_address(cls.warehouse, "_Test Auto PO Warehouse Address")

		cls.secondary_warehouse_name = f"_Test Auto PO Warehouse 2 - {frappe.db.get_value('Company', cls.company, 'abbr')}"
		if not frappe.db.exists("Warehouse", cls.secondary_warehouse_name):
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "_Test Auto PO Warehouse 2",
					"company": cls.company,
				}
			).insert(ignore_permissions=True)
		cls.secondary_warehouse = cls.secondary_warehouse_name
		cls._ensure_warehouse_address(cls.secondary_warehouse, "_Test Auto PO Warehouse Address 2")

	@classmethod
	def _ensure_supplier(cls, supplier_name):
		supplier = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
		if supplier:
			return supplier
		try:
			doc = frappe.get_doc(
				{"doctype": "Supplier", "supplier_name": supplier_name, "supplier_group": "Services"}
			).insert(ignore_permissions=True)
			return doc.name
		except Exception:
			supplier = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
			if supplier:
				return supplier
			return supplier_name

	@classmethod
	def _ensure_warehouse_address(cls, warehouse, title):
		if frappe.db.exists("Dynamic Link", {"link_doctype": "Warehouse", "link_name": warehouse, "parenttype": "Address"}):
			return
		if frappe.db.exists("Address", title):
			return
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_type": "Shipping",
				"address_line1": "Test Line 1",
				"city": "Chennai",
				"state": "Tamil Nadu",
				"pincode": "600001",
				"country": "India",
				"links": [{"link_doctype": "Warehouse", "link_name": warehouse}],
			}
		)
		address.insert(ignore_permissions=True)

	@classmethod
	def _ensure_item(cls, item_code, supplier):
		if not frappe.db.exists("Item", item_code):
			if not frappe.db.exists("GST HSN Code", "999999"):
				frappe.get_doc(
					{
						"doctype": "GST HSN Code",
						"hsn_code": "999999",
						"description": "Test HSN Code",
					}
				).insert(ignore_permissions=True)

			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": item_code,
					"item_name": item_code,
					"item_group": "Products",
					"is_stock_item": 1,
					"stock_uom": "Nos",
					"gst_hsn_code": "999999",
					"uoms": [{"uom": "Nos", "conversion_factor": 1.0}],
				}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("Item Supplier", {"parent": item_code, "supplier": supplier}):
			item_doc = frappe.get_doc("Item", item_code)
			item_doc.append("supplier_items", {"supplier": supplier})
			item_doc.save(ignore_permissions=True)

		return frappe.db.get_value("Item", item_code, "name")

	def _make_mr(self, rows, set_warehouse=None):
		mr = frappe.get_doc(
			{
				"doctype": "Material Request",
				"material_request_type": "Purchase",
				"company": self.company,
				"transaction_date": frappe.utils.today(),
				"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
				"set_warehouse": set_warehouse,
				"items": rows,
			}
		).insert(ignore_permissions=True)
		mr.submit()
		return mr

	def _get_po_items(self, mr_name):
		return frappe.get_all(
			"Purchase Order Item",
			filters={"material_request": mr_name},
			fields=["parent", "warehouse", "item_code", "qty"],
			as_list=False,
		)

	def test_01_auto_po_created_on_mr_submit(self):
		mr = self._make_mr(
			[
				{
					"item_code": self.item,
					"qty": 10,
					"uom": "Nos",
					"warehouse": self.warehouse,
					"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
				}
			],
			set_warehouse=self.warehouse,
		)

		po_item = frappe.db.get_value(
			"Purchase Order Item",
			{"material_request": mr.name, "item_code": self.item},
			["parent", "qty", "warehouse"],
			as_dict=True,
		)
		self.assertTrue(po_item, "Purchase Order was not automatically created from Material Request.")

		po = frappe.get_doc("Purchase Order", po_item.parent)
		self.assertEqual(po.docstatus, 0, "Generated PO should be in Draft state.")
		self.assertEqual(po.supplier, self.supplier, "Generated PO has incorrect supplier.")
		self.assertEqual(po.set_warehouse, self.warehouse, "Generated PO did not inherit set_warehouse from MR.")
		self.assertEqual(po_item.qty, 10, "Generated PO item quantity mismatch.")
		self.assertEqual(po_item.warehouse, self.warehouse, "Generated PO item warehouse mismatch.")
		self.assertTrue(
			frappe.db.exists("Dynamic Link", {"link_doctype": "Warehouse", "link_name": self.warehouse, "parenttype": "Address"}),
			"Generated PO warehouse should have a linked Address for Ship To rendering.",
		)

	def test_02_auto_po_splits_by_warehouse_and_supplier(self):
		mr = self._make_mr(
			[
				{
					"item_code": self.item,
					"qty": 4,
					"uom": "Nos",
					"warehouse": self.warehouse,
					"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
				},
				{
					"item_code": self.secondary_item,
					"qty": 6,
					"uom": "Nos",
					"warehouse": self.secondary_warehouse,
					"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
				},
			]
		)

		po_items = self._get_po_items(mr.name)
		self.assertEqual(len(po_items), 2, "Expected one PO item row per warehouse/supplier group.")

		po_names = sorted({row.parent for row in po_items})
		self.assertEqual(len(po_names), 2, "Expected two draft POs for two warehouse/supplier groups.")

		po_warehouses = {name: frappe.db.get_value("Purchase Order", name, "set_warehouse") for name in po_names}
		self.assertIn(self.warehouse, po_warehouses.values())
		self.assertIn(self.secondary_warehouse, po_warehouses.values())

		for row in po_items:
			po = frappe.get_doc("Purchase Order", row.parent)
			self.assertEqual(po.docstatus, 0)
			self.assertIn(po.set_warehouse, {self.warehouse, self.secondary_warehouse})
			self.assertEqual(row.warehouse, po.set_warehouse)
			if row.item_code == self.item:
				self.assertEqual(po.supplier, self.supplier)
			elif row.item_code == self.secondary_item:
				self.assertEqual(po.supplier, self.second_supplier)

	def test_03_auto_po_splits_by_supplier_within_same_warehouse(self):
		mr = self._make_mr(
			[
				{
					"item_code": self.item,
					"qty": 3,
					"uom": "Nos",
					"warehouse": self.warehouse,
					"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
				},
				{
					"item_code": self.secondary_item,
					"qty": 5,
					"uom": "Nos",
					"warehouse": self.warehouse,
					"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
				},
			]
		)

		po_items = self._get_po_items(mr.name)
		self.assertEqual(len(po_items), 2, "Expected separate POs when a warehouse has multiple suppliers.")
		for row in po_items:
			po = frappe.get_doc("Purchase Order", row.parent)
			self.assertEqual(po.set_warehouse, self.warehouse)
			self.assertEqual(row.warehouse, self.warehouse)

	def test_04_idempotency_prevents_duplicate_pos(self):
		mr = self._make_mr(
			[
				{
					"item_code": self.item,
					"qty": 5,
					"uom": "Nos",
					"warehouse": self.warehouse,
					"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
				},
			]
		)

		initial_count = frappe.db.count("Purchase Order Item", {"material_request": mr.name})
		self.assertEqual(initial_count, 1)

		auto_create_po(mr, "on_submit")

		final_count = frappe.db.count("Purchase Order Item", {"material_request": mr.name})
		self.assertEqual(final_count, 1, "Duplicate PO was generated for the same MR group.")

	def test_05_single_supplier_constraint_blocks_automation(self):
		second_supplier_name = self.second_supplier
		if not frappe.db.exists("Item Supplier", {"parent": self.item_code, "supplier": second_supplier_name}):
			item_doc = frappe.get_doc("Item", self.item_code)
			item_doc.append("supplier_items", {"supplier": second_supplier_name})
			item_doc.save(ignore_permissions=True)

		try:
			mr = frappe.get_doc(
				{
					"doctype": "Material Request",
					"material_request_type": "Purchase",
					"company": self.company,
					"transaction_date": frappe.utils.today(),
					"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
					"set_warehouse": self.warehouse,
					"items": [
						{
							"item_code": self.item,
							"qty": 3,
							"uom": "Nos",
							"warehouse": self.warehouse,
							"schedule_date": frappe.utils.add_days(frappe.utils.today(), 2),
						}
					],
				}
			).insert(ignore_permissions=True)
			mr.submit()

			po_count = frappe.db.count("Purchase Order Item", {"material_request": mr.name})
			self.assertEqual(po_count, 0, "PO was auto-created despite item having multiple suppliers.")
		finally:
			frappe.db.delete("Item Supplier", {"parent": self.item_code, "supplier": second_supplier_name})
			frappe.db.commit()

	def test_06_po_pdf_uses_supplier_gstin_password(self):
		supplier_name = self.supplier
		frappe.db.set_value("Supplier", supplier_name, "tax_id", "33AAGCR8772D1Z9")

		po = SimpleNamespace(name="PUR-ORD-TEST-0001", supplier=supplier_name)

		with patch("frappe.utils.print_utils.attach_print") as mock_attach_print:
			mock_attach_print.return_value = {"fname": "PUR-ORD-TEST-0001.pdf", "fcontent": b"pdf"}
			attachment = material_request.build_po_pdf_attachment(po)

		mock_attach_print.assert_called_once()
		_, kwargs = mock_attach_print.call_args
		self.assertEqual(kwargs["doctype"], "Purchase Order")
		self.assertEqual(kwargs["name"], "PUR-ORD-TEST-0001")
		self.assertEqual(kwargs["print_format"], "GST Purchase Order")
		self.assertEqual(kwargs["password"], "33AAGCR8772D1Z9")
		self.assertEqual(attachment["fname"], "PUR-ORD-TEST-0001.pdf")

	def test_07_po_pdf_falls_back_to_supplier_name_password(self):
		supplier_name = self.supplier
		frappe.db.set_value("Supplier", supplier_name, "tax_id", "")
		frappe.db.set_value("Supplier", supplier_name, "gstin", "")
		frappe.db.set_value("Supplier", supplier_name, "supplier_name", "S 1@u_pp!?")

		fallback = material_request.build_supplier_fallback_password(supplier_name)
		self.assertEqual(fallback, "SUPP1234")

		po = SimpleNamespace(name="PUR-ORD-TEST-0002", supplier=supplier_name)
		with patch("frappe.utils.print_utils.attach_print") as mock_attach_print:
			mock_attach_print.return_value = {"fname": "PUR-ORD-TEST-0002.pdf", "fcontent": b"pdf"}
			material_request.build_po_pdf_attachment(po)

		_, kwargs = mock_attach_print.call_args
		self.assertEqual(kwargs["password"], "SUPP1234")
