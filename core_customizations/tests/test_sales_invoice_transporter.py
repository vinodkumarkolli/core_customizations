# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import json
import re
import frappe
from frappe.tests import IntegrationTestCase


class TestSalesInvoiceTransporter(IntegrationTestCase):
	"""
	Test suite for Transporter & Godown Delivery custom fields,
	validations, address display formatting, and Print Formats on Sales Invoice.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.print_formats = [
			"GST Invoice - Original for Receiver",
			"GST Invoice - Triplicate for Supplier",
			"GST Invoice - Duplicate for Transporter",
		]

		# Create a test transporter supplier if not present
		cls.transporter_name = "_Test Transporter Supplier"
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
		cls.from_address_title = "_Test Transporter Origin Hub"
		cls.from_address_name = cls._create_test_address(
			cls.from_address_title,
			cls.transporter_name,
			"100 Booking Street, Hub Area",
			"Chennai",
			"Tamil Nadu",
			"600001",
		)

		cls.to_address_title = "_Test Transporter Destination Godown"
		cls.to_address_name = cls._create_test_address(
			cls.to_address_title,
			cls.transporter_name,
			"200 Delivery Road, Godown Zone",
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

	def test_01_custom_fields_exist_on_sales_invoice(self):
		"""Verify all required Transporter and Godown delivery custom fields exist."""
		expected_fields = {
			"custom_transporter_section": ("Section Break", None),
			"custom_transporter": ("Link", "Supplier"),
			"custom_transporter_from_address": ("Link", "Address"),
			"custom_transporter_from_address_display": ("Small Text", None),
			"custom_transporter_col_break": ("Column Break", None),
			"custom_is_godown_delivery": ("Check", None),
			"custom_transporter_to_address": ("Link", "Address"),
			"custom_transporter_to_address_display": ("Small Text", None),
		}

		meta = frappe.get_meta("Sales Invoice")
		for fieldname, (fieldtype, options) in expected_fields.items():
			field = meta.get_field(fieldname)
			self.assertIsNotNone(field, f"Field '{fieldname}' missing on Sales Invoice")
			self.assertEqual(field.fieldtype, fieldtype, f"Field '{fieldname}' fieldtype mismatch")
			if options:
				self.assertEqual(field.options, options, f"Field '{fieldname}' options mismatch")

	def test_02_field_order_property_setter_includes_all_transporter_fields(self):
		"""Verify field_order Property Setter includes transporter fields in sequence."""
		if frappe.db.exists("Property Setter", "Sales Invoice-main-field_order"):
			ps = frappe.get_doc("Property Setter", "Sales Invoice-main-field_order")
			order = json.loads(ps.value)

			expected_sequence = [
				"custom_transporter_section",
				"custom_transporter",
				"custom_transporter_from_address",
				"custom_transporter_from_address_display",
				"custom_transporter_col_break",
				"custom_is_godown_delivery",
				"custom_transporter_to_address",
				"custom_transporter_to_address_display",
			]

			for f in expected_sequence:
				self.assertIn(f, order, f"Field '{f}' is missing from field_order Property Setter")

			# Verify sequence order
			indices = [order.index(f) for f in expected_sequence]
			self.assertEqual(indices, sorted(indices), "Transporter fields are not in correct consecutive order")

	def test_03_address_query_filters_transporter_addresses(self):
		"""Verify address_query only returns addresses linked to the selected transporter."""
		from frappe.contacts.doctype.address.address import address_query

		results = address_query(
			doctype="Address",
			txt="",
			searchfield="name",
			start=0,
			page_len=10,
			filters={"link_doctype": "Supplier", "link_name": self.transporter_name},
		)

		result_names = [r[0] for r in results]
		self.assertIn(self.from_address_name, result_names)
		self.assertIn(self.to_address_name, result_names)

	def test_04_address_display_formatting_strips_raw_br_tags(self):
		"""Verify formatted address displays clean newlines without raw HTML <br> tags."""
		from frappe.contacts.doctype.address.address import get_address_display

		addr_doc = frappe.get_doc("Address", self.from_address_name)
		raw_display = get_address_display(addr_doc.as_dict())

		# Simulate the clean transformation applied by the Client Script
		clean_display = re.sub(r"<br\s*/?>", "\n", raw_display, flags=re.IGNORECASE).strip()
		clean_display = re.sub(r"\n+", "\n", clean_display)

		self.assertNotIn("<br>", clean_display)
		self.assertNotIn("<br/>", clean_display)
		self.assertIn("Chennai", clean_display)
