# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import json
import frappe
from frappe.tests import IntegrationTestCase


class TestGSTInvoicePrintFormats(IntegrationTestCase):
	"""
	Dedicated test suite for GST Invoice Print Formats on Sales Invoice:
	1. GST Invoice - Original for Receiver (Original for Customer)
	2. GST Invoice - Duplicate for Transporter
	3. GST Invoice - Triplicate for Supplier
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.print_formats = [
			"GST Invoice - Original for Receiver",
			"GST Invoice - Duplicate for Transporter",
			"GST Invoice - Triplicate for Supplier",
		]

		# Create a test transporter supplier if not present
		cls.transporter_name = "_Test GST Transporter"
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
		cls.from_address_title = "_Test GST Origin Hub"
		cls.from_address_name = cls._create_test_address(
			cls.from_address_title,
			cls.transporter_name,
			"100 Transporter Origin Hub Street",
			"Chennai",
			"Tamil Nadu",
			"600001",
		)

		cls.to_address_title = "_Test GST Destination Godown"
		cls.to_address_name = cls._create_test_address(
			cls.to_address_title,
			cls.transporter_name,
			"200 Destination Godown Road",
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
			self.skipTest("No Sales Invoice available for testing GST Invoice prints")
		inv = frappe.get_doc("Sales Invoice", invoices[0].name)
		return inv

	def test_01_all_gst_print_formats_exist(self):
		"""Verify all 3 GST Print Formats exist with correct configuration and module."""
		for pf_name in self.print_formats:
			self.assertTrue(frappe.db.exists("Print Format", pf_name), f"Print Format '{pf_name}' not found")
			pf = frappe.get_doc("Print Format", pf_name)
			self.assertEqual(pf.doc_type, "Sales Invoice")
			self.assertEqual(pf.module, "Core Customizations")
			self.assertEqual(pf.print_format_type, "Jinja")
			self.assertEqual(pf.font, "DM Sans")
			self.assertEqual(pf.print_format_builder_beta, 1)

	def test_02_print_formats_headings_intact(self):
		"""Verify each print format retains its distinct, required header label."""
		expected_headings = {
			"GST Invoice - Original for Receiver": "Original for Customer",
			"GST Invoice - Duplicate for Transporter": "Duplicate for Transporter",
			"GST Invoice - Triplicate for Supplier": "Triplicate for Supplier",
		}

		for pf_name, heading in expected_headings.items():
			pf = frappe.get_doc("Print Format", pf_name)
			format_data = pf.format_data or ""
			classic_data = pf.classic_format_data or ""
			header_found = heading in format_data or heading in classic_data
			self.assertTrue(header_found, f"Expected heading '{heading}' missing in Print Format '{pf_name}'")

	def test_03_original_for_receiver_renders(self):
		"""Verify GST Invoice - Original for Receiver renders with all key sections."""
		inv = self._get_test_invoice()
		html = frappe.get_print("Sales Invoice", inv.name, print_format="GST Invoice - Original for Receiver")

		self.assertIn("Original for Customer", html)
		self.assertIn(inv.name, html)
		self.assertIn(inv.company, html)
		self.assertIn("Bank Details", html)

	def test_04_duplicate_for_transporter_renders(self):
		"""Verify GST Invoice - Duplicate for Transporter renders with correct header."""
		inv = self._get_test_invoice()
		html = frappe.get_print("Sales Invoice", inv.name, print_format="GST Invoice - Duplicate for Transporter")

		self.assertIn("Duplicate for Transporter", html)
		self.assertIn(inv.name, html)
		self.assertIn("Bank Details", html)

	def test_05_triplicate_for_supplier_renders(self):
		"""Verify GST Invoice - Triplicate for Supplier renders with correct header."""
		inv = self._get_test_invoice()
		html = frappe.get_print("Sales Invoice", inv.name, print_format="GST Invoice - Triplicate for Supplier")

		self.assertIn("Triplicate for Supplier", html)
		self.assertIn(inv.name, html)
		self.assertIn("Bank Details", html)

	def test_06_bank_details_rendering_across_all_three(self):
		"""Verify all 3 GST formats render Bank Details cleanly without transporter section."""
		inv = self._get_test_invoice()

		for pf_name in self.print_formats:
			html = frappe.get_print("Sales Invoice", inv.name, print_format=pf_name)
			self.assertIn("Bank Details", html, f"Bank Details missing in '{pf_name}'")
			self.assertIn("document-footer-content", html, f"Footer missing in '{pf_name}'")
			self.assertNotIn("<b>Transporter:</b>", html, f"Transporter should not appear below Bank Details in '{pf_name}'")

