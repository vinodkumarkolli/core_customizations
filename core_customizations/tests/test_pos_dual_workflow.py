# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate, nowtime, flt, cint
from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import make_closing_entry_from_opening


class TestPOSDualWorkflow(IntegrationTestCase):
	"""
	Integration test suite verifying the Dual Sales Architecture:
	1. Wholesale / 3PL Dispatch Flow: SO -> DN (Stock & Batches Updated) -> SI (update_stock = 0).
	2. Retail / POS Flow: POS -> POS Invoice -> POS Closing Entry -> Consolidated Sales Invoice.
	3. Sales Returns: Delivery Note Return (Stock) + Sales Invoice Credit Note (Accounting), and POS Return.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1)[0].name

		# 1. Create a Test POS Profile if not present
		cls.pos_profile_name = "_Test POS Profile"
		cls.warehouse = "Stores - SE-K"
		if not frappe.db.exists("Warehouse", cls.warehouse):
			cls.warehouse = frappe.get_all("Warehouse", filters={"company": cls.company, "is_group": 0}, limit=1)[0].name

		cls.customer = "_Test POS Customer"
		if not frappe.db.exists("Customer", cls.customer):
			frappe.get_doc({
				"doctype": "Customer",
				"customer_name": cls.customer,
				"customer_group": "Commercial",
				"territory": "All Territories",
				"default_price_list": "Standard Selling",
			}).insert(ignore_permissions=True)


		cls.item_code = "_Test_POS_Item"
		if not frappe.db.exists("Item", cls.item_code):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": cls.item_code,
				"item_name": "Test POS Item",
				"item_group": "Products",
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"gst_hsn_code": "85395000",
			}).insert(ignore_permissions=True)


		cls._setup_pos_profile()
		cls._setup_pos_opening_entry()

	@classmethod
	def _setup_pos_opening_entry(cls):
		existing = frappe.get_all(
			"POS Opening Entry",
			filters={"pos_profile": cls.pos_profile_name, "status": "Open", "docstatus": 1},
			limit=1
		)
		if not existing:
			entry = frappe.get_doc({
				"doctype": "POS Opening Entry",
				"period_start_date": nowdate(),
				"pos_profile": cls.pos_profile_name,
				"user": frappe.session.user,
				"company": cls.company,
				"balance_details": [{
					"mode_of_payment": "Cash",
					"opening_amount": 1000
				}]
			}).insert(ignore_permissions=True)
			entry.submit()

	@classmethod
	def _setup_pos_profile(cls):
		if not frappe.db.exists("POS Profile", cls.pos_profile_name):
			cash_account = frappe.db.get_value("Account", {"account_type": "Cash", "company": cls.company}, "name")
			if not cash_account:
				cash_account = frappe.db.get_value("Account", {"is_group": 0, "company": cls.company}, "name")

			cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
			if not cost_center:
				ccs = frappe.get_all("Cost Center", filters={"company": cls.company, "is_group": 0}, limit=1)
				cost_center = ccs[0].name if ccs else None

			write_off_account = frappe.db.get_value("Company", cls.company, "write_off_account")
			if not write_off_account:
				wo_accs = frappe.get_all("Account", filters={"company": cls.company, "is_group": 0, "root_type": "Expense"}, limit=1)
				write_off_account = wo_accs[0].name if wo_accs else cash_account

			pos_prof = frappe.get_doc({
				"doctype": "POS Profile",
				"name": cls.pos_profile_name,
				"company": cls.company,
				"warehouse": cls.warehouse,
				"customer": cls.customer,
				"write_off_account": write_off_account,
				"write_off_cost_center": cost_center,
				"cost_center": cost_center,
				"payments": [{
					"mode_of_payment": "Cash",
					"default": 1,
					"account": cash_account
				}]
			})
			pos_prof.insert(ignore_permissions=True)

	def test_01_wholesale_flow_requires_delivery_note(self):
		"""Verify standard Sales Invoice cannot be created without a linked Delivery Note."""
		si = frappe.get_doc({
			"doctype": "Sales Invoice",
			"company": self.company,
			"customer": self.customer,
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"items": [{
				"item_code": self.item_code,
				"qty": 10,
				"rate": 100,
			}]
		})
		si.flags.ignore_mandatory = True

		with self.assertRaises(frappe.ValidationError) as ctx:
			si.insert(ignore_permissions=True)
		self.assertIn("Delivery Note is mandatory", str(ctx.exception))

	def test_02_wholesale_flow_disallows_update_stock_on_sales_invoice(self):
		"""Verify Sales Invoice with linked Delivery Note disallows update_stock = 1."""
		dn = frappe.get_doc({
			"doctype": "Delivery Note",
			"company": self.company,
			"customer": self.customer,
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"items": [{
				"item_code": self.item_code,
				"qty": 10,
				"warehouse": self.warehouse,
			}]
		})
		dn.flags.ignore_mandatory = True
		dn.insert(ignore_permissions=True)

		si = frappe.get_doc({
			"doctype": "Sales Invoice",
			"company": self.company,
			"customer": self.customer,
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"update_stock": 1,
			"items": [{
				"item_code": self.item_code,
				"qty": 10,
				"rate": 100,
				"delivery_note": dn.name,
				"dn_detail": dn.items[0].name,
			}]
		})
		si.flags.ignore_mandatory = True

		with self.assertRaises(frappe.ValidationError) as ctx:
			si.insert(ignore_permissions=True)
		self.assertTrue(
			"Update Stock cannot be enabled" in str(ctx.exception)
			or "Stock cannot be updated against the following Delivery Notes" in str(ctx.exception)
		)


	def test_03_wholesale_flow_successful_with_delivery_note(self):
		"""Verify Sales Invoice succeeds when linked to Delivery Note and update_stock = 0."""
		dn = frappe.get_doc({
			"doctype": "Delivery Note",
			"company": self.company,
			"customer": self.customer,
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"items": [{
				"item_code": self.item_code,
				"qty": 10,
				"warehouse": self.warehouse,
			}]
		})
		dn.flags.ignore_mandatory = True
		dn.insert(ignore_permissions=True)

		si = frappe.get_doc({
			"doctype": "Sales Invoice",
			"company": self.company,
			"customer": self.customer,
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"update_stock": 0,
			"items": [{
				"item_code": self.item_code,
				"qty": 10,
				"rate": 100,
				"delivery_note": dn.name,
				"dn_detail": dn.items[0].name,
			}]
		})
		si.flags.ignore_mandatory = True
		si.insert(ignore_permissions=True)
		self.assertTrue(si.name)

	def test_04_sales_invoice_credit_note_bypasses_delivery_note_requirement(self):
		"""Verify Return / Credit Note Sales Invoice (is_return = 1) succeeds without Delivery Note."""
		si_return = frappe.get_doc({
			"doctype": "Sales Invoice",
			"company": self.company,
			"customer": self.customer,
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"is_return": 1,
			"update_stock": 0,
			"items": [{
				"item_code": self.item_code,
				"qty": -5,
				"rate": 100,
			}]
		})
		si_return.flags.ignore_mandatory = True
		si_return.insert(ignore_permissions=True)
		self.assertTrue(si_return.name)

	def test_05_pos_invoice_creation_and_exemption(self):
		"""Verify POS Invoice creates successfully and is exempted from Delivery Note validation."""
		pos_inv = frappe.get_doc({
			"doctype": "POS Invoice",
			"company": self.company,
			"customer": self.customer,
			"pos_profile": self.pos_profile_name,
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"update_stock": 1,
			"items": [{
				"item_code": self.item_code,
				"qty": 2,
				"rate": 150,
				"warehouse": self.warehouse,
			}],
			"payments": [{
				"mode_of_payment": "Cash",
				"amount": 300,
				"default": 1,
			}]
		})
		pos_inv.flags.ignore_mandatory = True
		pos_inv.insert(ignore_permissions=True)
		self.assertTrue(pos_inv.name)
		self.assertEqual(pos_inv.is_pos, 1)

	def test_06_consolidated_pos_sales_invoice_bypasses_delivery_note(self):
		"""Verify Consolidated Sales Invoice created from POS Merge Log (is_consolidated = 1) is allowed."""
		pos_inv = frappe.get_doc({
			"doctype": "POS Invoice",
			"company": self.company,
			"customer": self.customer,
			"pos_profile": self.pos_profile_name,
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"update_stock": 1,
			"items": [{
				"item_code": self.item_code,
				"qty": 3,
				"rate": 150,
				"warehouse": self.warehouse,
			}],
			"payments": [{
				"mode_of_payment": "Cash",
				"amount": 450,
				"default": 1,
			}]
		})
		pos_inv.flags.ignore_mandatory = True
		pos_inv.insert(ignore_permissions=True)

		# Create simulated Consolidated Sales Invoice as created by POS Closing Entry / Merge Log
		si_consolidated = frappe.get_doc({
			"doctype": "Sales Invoice",
			"company": self.company,
			"customer": self.customer,
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"is_pos": 1,
			"is_consolidated": 1,
			"update_stock": 0,
			"items": [{
				"item_code": self.item_code,
				"qty": 3,
				"rate": 150,
				"amount": 450,
				"base_amount": 450,
				"net_amount": 450,
				"base_net_amount": 450,
				"pos_invoice": pos_inv.name,
				"pos_invoice_item": pos_inv.items[0].name,
			}]
		})
		si_consolidated.flags.ignore_mandatory = True
		si_consolidated.insert(ignore_permissions=True)
		self.assertTrue(si_consolidated.name)

	def test_07_cancellation_dependency_checks_chain(self):
		"""Verify upstream documents cannot be cancelled while downstream documents are active (SO <- DN <- SI)."""
		# 1. Create and submit Sales Order
		so = frappe.get_doc({
			"doctype": "Sales Order",
			"company": self.company,
			"customer": self.customer,
			"delivery_date": nowdate(),
			"items": [{
				"item_code": self.item_code,
				"qty": 5,
				"rate": 100,
				"item_tax_template": "GST 18% - SE-K",
			}]
		})
		so.flags.ignore_mandatory = True
		so.insert(ignore_permissions=True)
		so.submit()

		# 2. Create and submit Delivery Note against SO
		dn = frappe.get_doc({
			"doctype": "Delivery Note",
			"company": self.company,
			"customer": self.customer,
			"items": [{
				"item_code": self.item_code,
				"qty": 5,
				"rate": 100,
				"warehouse": self.warehouse,
				"against_sales_order": so.name,
				"so_detail": so.items[0].name,
				"item_tax_template": "GST 18% - SE-K",
			}]
		})
		dn.flags.ignore_mandatory = True
		dn.insert(ignore_permissions=True)
		dn.submit()


		# 3. Assert: Upstream SO CANNOT be cancelled while downstream DN is active (submitted)
		with self.assertRaises(Exception):
			so.cancel()

		# 4. Create and submit Sales Invoice against DN
		si = frappe.get_doc({
			"doctype": "Sales Invoice",
			"company": self.company,
			"customer": self.customer,
			"update_stock": 0,
			"items": [{
				"item_code": self.item_code,
				"qty": 5,
				"rate": 100,
				"delivery_note": dn.name,
				"dn_detail": dn.items[0].name,
				"sales_order": so.name,
				"so_detail": so.items[0].name,
				"item_tax_template": "GST 18% - SE-K",
			}]
		})
		si.flags.ignore_mandatory = True
		si.insert(ignore_permissions=True)
		si.submit()


		# 5. Assert: Upstream DN CANNOT be cancelled while downstream SI is active (submitted)
		with self.assertRaises(Exception):
			dn.cancel()

		# 6. Assert: Upstream SO CANNOT be cancelled while downstream SI and DN are active
		with self.assertRaises(Exception):
			so.cancel()

		# 7. Reverse cancellation sequence:
		# A. Cancel downstream Sales Invoice first (succeeds)
		si.reload()
		si.cancel()
		self.assertEqual(si.docstatus, 2)

		# B. Cancel Delivery Note next (succeeds, reverses stock and auto-cancels packing slips)
		dn.reload()
		dn.cancel()
		self.assertEqual(dn.docstatus, 2)

		# C. Cancel Sales Order last (succeeds once all downstream docs are cancelled)
		so.reload()
		so.cancel()
		self.assertEqual(so.docstatus, 2)



