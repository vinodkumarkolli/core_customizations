# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from core_customizations.monkey_patches import custom_update_stock, custom_validate_delivery_note, custom_validate_items
from core_customizations.tests.test_fixtures import ensure_test_fixtures


class TestMonkeyPatches(FrappeTestCase):
	"""
	Tests for monkey patches:
	1. custom_update_stock (batch allocation, serial nos, context filtering)
	2. custom_validate_delivery_note (packing slip lifecycle: Draft/Submitted allowed, Cancelled blocked)
	3. custom_validate_items (packing slip dn_detail linkage)
	"""

	def setUp(self):
		# Ensure ERPNext master data exists in the blank CI environment
		ensure_test_fixtures()

		# Resolve company and warehouse dynamically — the CI site has a single
		# company created by ERPNext install, but it may have a different name
		# than the production company "Sravi Enterprises - Kolapakkam".
		self.company = frappe.db.get_value("Company", {}, "name") or "Test Company"
		self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name") or "Stores - TC"
		self.customer = self._get_or_create_customer()
		self.item_code = self._get_or_create_item()

	def _get_or_create_customer(self):
		cust_name = "Test Monkey Patch Customer"
		if not frappe.db.exists("Customer", cust_name):
			frappe.get_doc({
				"doctype": "Customer",
				"customer_name": cust_name,
				"customer_group": "Commercial",
				"customer_type": "Company",
				"territory": "India",
				"default_price_list": "Standard Selling"
			}).insert(ignore_permissions=True)
		return cust_name

	def _get_or_create_item(self):
		item_code = "TEST-MP-NONBATCH"
		if not frappe.db.exists("Item", item_code):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": "Test Monkey Patch NonBatch Item",
				"item_group": "Products",
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"has_batch_no": 0,
				"has_serial_no": 0,
				"gst_hsn_code": "85395000"
			}).insert(ignore_permissions=True)
		return item_code

	def _create_delivery_note(self):
		dn = frappe.get_doc({
			"doctype": "Delivery Note",
			"company": self.company,
			"customer": self.customer,
			"set_warehouse": self.warehouse,
			"items": [
				{
					"item_code": self.item_code,
					"qty": 50,
					"rate": 100,
					"warehouse": self.warehouse
				}
			]
		})
		dn.insert(ignore_permissions=True)
		return dn

	def test_01_update_stock_context_delivery_note(self):
		"""Verify custom_update_stock handles Delivery Note context gracefully."""
		ctx = frappe._dict({
			"doctype": "Delivery Note",
			"item_code": self.item_code,
			"warehouse": self.warehouse,
			"child_docname": "test_row_1"
		})
		out = frappe._dict({
			"warehouse": self.warehouse,
			"stock_qty": 10,
			"uom": "Nos",
			"item_code": self.item_code,
			"has_batch_no": 0,
			"has_serial_no": 0
		})
		doc = frappe._dict({
			"name": "DN-TEST-001",
			"selling_price_list": "Standard Selling"
		})

		# Should execute without throwing errors
		custom_update_stock(ctx, out, doc)

	def test_02_update_stock_ignored_for_sales_invoice_without_stock_update(self):
		"""Verify custom_update_stock is ignored for standard wholesale Sales Invoices (update_stock=0)."""
		ctx = frappe._dict({
			"doctype": "Sales Invoice",
			"update_stock": 0,
			"item_code": self.item_code,
			"warehouse": self.warehouse
		})
		out = frappe._dict({
			"warehouse": self.warehouse,
			"stock_qty": 10,
			"uom": "Nos",
			"item_code": self.item_code,
			"has_batch_no": 1,
			"has_serial_no": 0,
			"batch_no": None
		})
		doc = frappe._dict({"name": "SI-TEST-001"})

		custom_update_stock(ctx, out, doc)
		# Batch allocation should not run
		self.assertIsNone(out.get("batch_no"))

	def test_03_custom_validate_delivery_note_on_packing_slip(self):
		"""Verify Packing Slip allows draft and submitted Delivery Notes, but blocks cancelled ones."""
		dn = self._create_delivery_note()

		# 1. Draft DN: should pass
		ps_mock = frappe.get_doc({
			"doctype": "Packing Slip",
			"delivery_note": dn.name,
			"from_package_no": 1,
			"to_package_no": 1
		})
		custom_validate_delivery_note(ps_mock)

		# 2. Mock Submitted DN docstatus = 1: should pass
		frappe.db.set_value("Delivery Note", dn.name, "docstatus", 1)
		custom_validate_delivery_note(ps_mock)

		# 3. Mock Cancelled DN docstatus = 2: should throw ValidationError
		frappe.db.set_value("Delivery Note", dn.name, "docstatus", 2)
		with self.assertRaises(frappe.ValidationError):
			custom_validate_delivery_note(ps_mock)

		# 4. Missing DN: should throw ValidationError
		ps_empty = frappe.get_doc({
			"doctype": "Packing Slip",
			"delivery_note": None,
			"from_package_no": 1,
			"to_package_no": 1
		})
		with self.assertRaises(frappe.ValidationError):
			custom_validate_delivery_note(ps_empty)

	def test_04_custom_validate_items_on_packing_slip(self):
		"""Verify Packing Slip items validation enforces valid dn_detail references."""
		dn = self._create_delivery_note()
		valid_dn_item = dn.items[0].name

		# Valid item linkage
		ps_valid = frappe.get_doc({
			"doctype": "Packing Slip",
			"delivery_note": dn.name,
			"from_package_no": 1,
			"to_package_no": 1,
			"items": [
				{"dn_detail": valid_dn_item, "item_code": self.item_code, "qty": 10}
			]
		})
		custom_validate_items(ps_valid)

		# Invalid item linkage
		ps_invalid = frappe.get_doc({
			"doctype": "Packing Slip",
			"delivery_note": dn.name,
			"from_package_no": 1,
			"to_package_no": 1,
			"items": [
				{"dn_detail": "INVALID-DN-ROW-ID", "item_code": self.item_code, "qty": 10}
			]
		})
		with self.assertRaises(frappe.ValidationError):
			custom_validate_items(ps_invalid)
