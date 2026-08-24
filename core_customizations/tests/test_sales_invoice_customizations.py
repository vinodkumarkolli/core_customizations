# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestSalesInvoiceCustomizations(FrappeTestCase):
	"""
	Test suite for custom fields, property setters, and validations on Sales Invoice.
	"""

	def test_sales_invoice_custom_fields(self):
		"""Verify custom fields exist on Sales Invoice."""
		meta = frappe.get_meta("Sales Invoice")
		
		field2 = meta.get_field("custom_is_godown_delivery")
		self.assertIsNotNone(field2, "Field 'custom_is_godown_delivery' missing on Sales Invoice")

	def test_02_standard_transporter_field_present(self):
		"""Verify standard ERPNext transporter field is present on Sales Invoice."""
		meta = frappe.get_meta("Sales Invoice")
		field = meta.get_field("transporter")
		self.assertIsNotNone(field, "Standard 'transporter' field missing on Sales Invoice")
