# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestPOSLabelPrintFormats(IntegrationTestCase):
	"""
	Dedicated test suite for Unified 4x6 Shipping Package Label Print Format on Delivery Note.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.label_format = "Shipping Package Label (4x6)"

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

	def _get_test_delivery_note(self, is_godown=1):
		notes = frappe.get_all("Delivery Note", limit=1)
		if not notes:
			self.skipTest("No Delivery Note available for testing POS label prints")
		dn = frappe.get_doc("Delivery Note", notes[0].name)
		dn.transporter = self.transporter_name
		dn.custom_transporter_from_address = self.from_address_name
		dn.custom_transporter_from_address_display = "500 Origin Booking Street\nChennai\nTamil Nadu"
		dn.custom_is_godown_delivery = 1 if is_godown else 0
		dn.custom_transporter_to_address = self.to_address_name if is_godown else None
		dn.custom_transporter_to_address_display = "800 Destination Delivery Road\nSalem\nTamil Nadu" if is_godown else None
		dn.db_update()
		return dn

	def test_01_unified_label_print_format_exists(self):
		"""Verify unified 4x6 Shipping Package Label Print Format exists with proper configuration on Delivery Note."""
		self.assertTrue(frappe.db.exists("Print Format", self.label_format), f"Print Format '{self.label_format}' does not exist")
		pf = frappe.get_doc("Print Format", self.label_format)
		self.assertEqual(pf.doc_type, "Delivery Note")
		self.assertEqual(pf.module, "Core Customizations")
		self.assertEqual(pf.print_format_type, "Jinja")
		self.assertEqual(pf.custom_format, 1)

	def test_02_shipping_label_godown_delivery(self):
		"""Verify Shipping Package Label renders Godown Delivery destination, transporter, sender, and reference box."""
		dn = self._get_test_delivery_note(is_godown=1)
		html = frappe.get_print("Delivery Note", dn.name, print_format=self.label_format)

		# Header & Info
		self.assertIn(dn.name, html)
		self.assertIn("BOX NUMBER / TOTAL", html)

		# Godown Delivery info
		self.assertIn("GODOWN PICKUP", html)
		self.assertIn("800 Destination Delivery Road", html)
		self.assertIn(dn.customer_name, html)

		# Transporter & Reference Routing Info
		self.assertIn(self.transporter_name, html)
		self.assertIn("500 Origin Booking Street", html)
		self.assertIn("REF / ROUTING CODE", html)

		# Company info
		self.assertIn(dn.company, html)

		# Confirm individual items rows are not listed in a table
		self.assertNotIn("<th>Item</th>", html)
		self.assertNotIn("<th>Qty</th>", html)
		self.assertNotIn("<th>Rate</th>", html)

	def test_03_shipping_label_door_delivery(self):
		"""Verify Shipping Package Label renders standard Door Delivery destination address."""
		dn = self._get_test_delivery_note(is_godown=0)
		html = frappe.get_print("Delivery Note", dn.name, print_format=self.label_format)

		self.assertIn("DOOR DELIVERY", html)
		self.assertIn(dn.customer_name, html)
		self.assertIn(dn.company, html)
		self.assertIn(dn.name, html)

	def test_04_carton_shipping_label_on_packing_slip_confidential_layout(self):
		"""Verify Carton Shipping Label (4x6) on Packing Slip renders confidential logistics layout without item contents."""
		dn = self._get_test_delivery_note(is_godown=1)

		ps = frappe.new_doc("Packing Slip")
		ps.delivery_note = dn.name
		rec_case = ps.get_recommended_case_no() or 1
		ps.from_case_no = rec_case
		ps.to_case_no = rec_case
		ps.append("items", {
			"item_code": dn.items[0].item_code,
			"item_name": dn.items[0].item_name,
			"qty": 10,
			"stock_uom": dn.items[0].uom or "Nos",
			"dn_detail": dn.items[0].name
		})
		ps.insert(ignore_permissions=True)

		html = frappe.get_print("Packing Slip", ps.name, print_format="Carton Shipping Label (4x6)", no_letterhead=1)

		self.assertIn("BOX NUMBER / TOTAL", html)
		self.assertIn("BOX [", html)
		self.assertIn("CONSIGNEE (CUSTOMER)", html)
		self.assertIn("GODOWN PICKUP", html)
		self.assertIn("SHIPPING & ROUTING DETAILS", html)
		self.assertIn("CONSIGNOR (SENDER)", html)
		self.assertIn(ps.name, html)
		self.assertIn(dn.name, html)
		# Confidentiality check: item contents are omitted from outer carton label
		self.assertNotIn("PACKAGE CONTENTS (ITEMS)", html)
		self.assertNotIn(dn.items[0].item_name, html)




