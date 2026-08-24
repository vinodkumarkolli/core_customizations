# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestSalesInvoiceCustomizations(FrappeTestCase):
	"""
	Test suite for custom fields, property setters, and validations on Sales Invoice.
	"""

	def test_01_custom_fields_exist_on_sales_invoice(self):
		"""Verify custom_sales_person field exists on Sales Invoice."""
		meta = frappe.get_meta("Sales Invoice")
		field = meta.get_field("custom_sales_person")
		self.assertIsNotNone(field, "Field 'custom_sales_person' missing on Sales Invoice")
		self.assertEqual(field.fieldtype, "Link")
		self.assertEqual(field.options, "User")

	def test_02_standard_transporter_field_present(self):
		"""Verify standard ERPNext transporter field is present on Sales Invoice."""
		meta = frappe.get_meta("Sales Invoice")
		field = meta.get_field("transporter")
		self.assertIsNotNone(field, "Standard 'transporter' field missing on Sales Invoice")
