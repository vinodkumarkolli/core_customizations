# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestPOSLabelPrintFormats(IntegrationTestCase):
	"""
	Dedicated test suite for POS / Label Print Formats on Sales Invoice:
	1. Customer Delivery Address Label
	2. Transporter Godown To Address Label
	3. Transporter From Address Label
	4. Company Address Label
	5. Invoice Detail Label
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.label_formats = [
			"Customer Delivery Address Label",
			"Transporter Godown To Address Label",
			"Transporter From Address Label",
			"Company Address Label",
			"Invoice Detail Label",
		]

		# Create a test transporter supplier if not present
		cls.transporter_name = "_Test POS Transporter"
		if not frappe.db.exists("Supplier", cls.transporter_name):
			cls.supplier_doc = frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": cls.transporter_name,
				"supplier_group": "Services",
				"is_transporter": 1,
			}).insert(ignore_permissions=True)
		else:
			cls.supplier_doc = frappe.get_doc("Supplier", cls.transporter_name)
			if not cls.supplier_doc.is_transporter:
				cls.supplier_doc.is_transporter = 1
				cls.supplier_doc.save(ignore_permissions=True)

		# Create test addresses for this transporter
		cls.from_address_title = "_Test POS Origin Hub"
		cls.from_address_name = cls._create_test_address(
			cls.from_address_title,
			cls.transporter_name,
			"500 Origin Booking Street",
			"Chennai",
			"Tamil Nadu",
			"600001",
		)

		cls.to_address_title = "_Test POS Destination Godown"
		cls.to_address_name = cls._create_test_address(
			cls.to_address_title,
			cls.transporter_name,
			"800 Destination Delivery Road",
			"Salem",
			"Tamil Nadu",
			"636001",
		)
		frappe.db.commit()

	@classmethod
	def _create_test_address(cls, title, supplier_name, line1, city, state, pincode):
		addr_name = frappe.db.get_value(
			"Dynamic Link",
			{"parenttype": "Address", "link_doctype": "Supplier", "link_name": supplier_name},
			"parent",
		)
		if addr_name and frappe.db.get_value("Address", addr_name, "address_title") == title:
			return addr_name

		addr = frappe.get_doc({
			"doctype": "Address",
			"address_title": title,
			"address_type": "Billing",
			"address_line1": line1,
			"city": city,
			"state": state,
			"pincode": pincode,
			"country": "India",
			"links": [{"link_doctype": "Supplier", "link_name": supplier_name}],
		}).insert(ignore_permissions=True)
		return addr.name

	def _get_test_invoice(self):
		invoices = frappe.get_all("Sales Invoice", limit=1)
		if not invoices:
			self.skipTest("No Sales Invoice available for testing POS label prints")
		inv = frappe.get_doc("Sales Invoice", invoices[0].name)
		inv.custom_transporter = self.transporter_name
		inv.custom_transporter_from_address = self.from_address_name
		inv.custom_transporter_from_address_display = "500 Origin Booking Street\nChennai\nTamil Nadu"
		inv.custom_is_godown_delivery = 1
		inv.custom_transporter_to_address = self.to_address_name
		inv.custom_transporter_to_address_display = "800 Destination Delivery Road\nSalem\nTamil Nadu"
		inv.db_update()
		return inv

	def test_01_all_label_print_formats_exist(self):
		"""Verify all 5 POS Label Print Formats exist with proper configuration."""
		for label in self.label_formats:
			self.assertTrue(frappe.db.exists("Print Format", label), f"Print Format '{label}' does not exist")
			pf = frappe.get_doc("Print Format", label)
			self.assertEqual(pf.doc_type, "Sales Invoice")
			self.assertEqual(pf.module, "Core Customizations")
			self.assertEqual(pf.print_format_type, "Jinja")
			self.assertEqual(pf.custom_format, 1)

	def test_02_customer_delivery_address_label(self):
		"""Verify Customer Delivery Address Label renders customer details and no items."""
		inv = self._get_test_invoice()
		html = frappe.get_print("Sales Invoice", inv.name, print_format="Customer Delivery Address Label")

		self.assertIn("Customer Delivery Address", html)
		self.assertIn(inv.customer_name, html)
		self.assertIn(inv.name, html)
		self.assertNotIn("<th>Item</th>", html)
		self.assertNotIn("<th>Qty</th>", html)

	def test_03_transporter_godown_to_address_label(self):
		"""Verify Transporter Godown To Address Label renders transporter destination godown."""
		inv = self._get_test_invoice()
		html = frappe.get_print("Sales Invoice", inv.name, print_format="Transporter Godown To Address Label")

		self.assertIn("Transporter Godown (To Address)", html)
		self.assertIn(self.transporter_name, html)
		self.assertIn("Destination Godown:", html)
		self.assertIn("800 Destination Delivery Road", html)
		self.assertIn(inv.name, html)
		self.assertNotIn("<th>Item</th>", html)

	def test_04_transporter_from_address_label(self):
		"""Verify Transporter From Address Label renders transporter origin booking hub."""
		inv = self._get_test_invoice()
		html = frappe.get_print("Sales Invoice", inv.name, print_format="Transporter From Address Label")

		self.assertIn("Transporter Booking (From Address)", html)
		self.assertIn(self.transporter_name, html)
		self.assertIn("Booking / Origin Hub:", html)
		self.assertIn("500 Origin Booking Street", html)
		self.assertIn(inv.name, html)
		self.assertNotIn("<th>Item</th>", html)

	def test_05_company_address_label(self):
		"""Verify Company Address Label renders sender company details."""
		inv = self._get_test_invoice()
		html = frappe.get_print("Sales Invoice", inv.name, print_format="Company Address Label")

		self.assertIn("From (Sender Address)", html)
		self.assertIn(inv.company, html)
		self.assertIn(inv.name, html)
		self.assertNotIn("<th>Item</th>", html)

	def test_06_invoice_detail_label(self):
		"""Verify Invoice Detail Label renders invoice summary without item rows/quantities."""
		inv = self._get_test_invoice()
		html = frappe.get_print("Sales Invoice", inv.name, print_format="Invoice Detail Label")

		self.assertIn("Invoice Details", html)
		self.assertIn(inv.name, html)
		self.assertIn(inv.customer_name, html)
		self.assertIn("Total Amount:", html)
		# Confirm items and quantities are omitted
		self.assertNotIn("<th>Item</th>", html)
		self.assertNotIn("<th>Qty</th>", html)
		self.assertNotIn("<th>Rate</th>", html)
