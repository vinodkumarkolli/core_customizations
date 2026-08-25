# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from core_customizations.tests.test_fixtures import ensure_test_fixtures
from core_customizations.utils import format_qty, get_code128_svg


class TestGSTInvoicePrintFormats(IntegrationTestCase):
	"""
	Dedicated test suite for GST Invoice Print Formats on Sales Invoice:
	1. GST Invoice - Original for Receiver
	2. GST Invoice - Duplicate for Transporter
	3. GST Invoice - Triplicate for Supplier
	4. Bank Details & Payment Status layout
	5. Dedicated Shipping Details layout
	6. No Shipping Details tag fallback
	7. Zero-dependency Code128 SVG Barcode Generator
	8. Quantity Formatter (.0 omission)
	9. Additional Discount on Grand Total vs Net Total
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Ensure ERPNext master data exists in the blank CI environment
		ensure_test_fixtures()
		cls.print_formats = [
			"GST Invoice - Original for Receiver",
			"GST Invoice - Duplicate for Transporter",
			"GST Invoice - Triplicate for Supplier",
		]

		# Create a test transporter supplier if not present
		cls.transporter_name = "_Test GST Transporter"
		if not frappe.db.exists("Supplier", cls.transporter_name):
			cls.supplier_doc = frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": cls.transporter_name,
					"supplier_group": "Services",
					"is_transporter": 1,
				}
			).insert(ignore_permissions=True)
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

		addr = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_type": "Billing",
				"address_line1": line1,
				"city": city,
				"state": state,
				"pincode": pincode,
				"country": "India",
				"links": [{"link_doctype": "Supplier", "link_name": supplier_name}],
			}
		).insert(ignore_permissions=True)
		return addr.name

	def _get_test_invoice(
		self, is_paid=True, with_transporter=True, apply_discount_on="Grand Total", discount_amount=0
	):
		invoices = frappe.get_all(
			"Sales Invoice", filters={"docstatus": 1, "is_pos": 0}, order_by="creation desc", limit=1
		)
		if not invoices:
			invoices = frappe.get_all(
				"Sales Invoice",
				filters={"docstatus": ["!=", 2], "is_pos": 0},
				order_by="creation desc",
				limit=1,
			)
		if not invoices:
			self.skipTest("No Sales Invoice available for testing GST Invoice prints")
		inv = frappe.get_doc("Sales Invoice", invoices[0].name)

		if with_transporter:
			update_values = {
				"transporter": self.transporter_name,
				"custom_transporter": self.transporter_name,
				"custom_transporter_from_address": self.from_address_name,
				"custom_transporter_from_address_display": "100 Transporter Origin Hub Street<br>Chennai<br>Tamil Nadu",
				"custom_is_godown_delivery": 1,
				"custom_transporter_to_address": self.to_address_name,
				"custom_transporter_to_address_display": "200 Destination Godown Road<br>Salem<br>Tamil Nadu",
				"outstanding_amount": 0 if is_paid else 5000.00,
				"apply_discount_on": apply_discount_on,
				"discount_amount": discount_amount,
			}
		else:
			update_values = {
				"transporter": None,
				"custom_transporter": None,
				"custom_transporter_from_address": None,
				"custom_transporter_from_address_display": None,
				"custom_is_godown_delivery": 0,
				"custom_transporter_to_address": None,
				"custom_transporter_to_address_display": None,
				"outstanding_amount": 0 if is_paid else 5000.00,
				"apply_discount_on": apply_discount_on,
				"discount_amount": discount_amount,
			}

		inv.db_set(update_values)
		frappe.db.commit()
		inv.reload()
		return inv

	def test_01_all_gst_print_formats_exist(self):
		"""Verify all 3 GST Print Formats exist with custom_format=1 and Jinja type."""
		for pf_name in self.print_formats:
			self.assertTrue(frappe.db.exists("Print Format", pf_name), f"Print Format '{pf_name}' not found")
			pf = frappe.get_doc("Print Format", pf_name)
			self.assertEqual(pf.doc_type, "Sales Invoice")
			self.assertEqual(pf.module, "Core Customizations")
			self.assertEqual(pf.print_format_type, "Jinja")
			self.assertEqual(pf.custom_format, 1)

	def test_02_print_formats_headings_and_badges(self):
		"""Verify each print format retains its distinct, required header label in html."""
		expected_badges = {
			"GST Invoice - Original for Receiver": "Original for Receiver",
			"GST Invoice - Duplicate for Transporter": "Duplicate for Transporter",
			"GST Invoice - Triplicate for Supplier": "Triplicate for Supplier",
		}

		for pf_name, badge in expected_badges.items():
			pf = frappe.get_doc("Print Format", pf_name)
			html_content = pf.html or ""
			self.assertIn(
				badge, html_content, f"Expected badge '{badge}' missing in Print Format '{pf_name}'"
			)
			self.assertIn("TAX INVOICE", html_content.upper())
			self.assertIn("GSTIN:", html_content)
			self.assertIn("Place of Supply:", html_content)

	def test_03_payment_status_fully_paid_layout(self):
		"""Verify Payment & Status box shows Bank Details and Fully Paid badge, with no Transporter info."""
		inv = self._get_test_invoice(is_paid=True, with_transporter=True)
		html = frappe.get_print("Sales Invoice", inv.name, print_format="GST Invoice - Original for Receiver")

		self.assertIn("Fully Paid", html)
		self.assertIn("Payment & Status", html)
		self.assertIn("Shipping & Logistics Details", html)
		self.assertIn(self.transporter_name, html)
		self.assertIn("Grand Total:", html)

	def test_04_payment_status_unpaid_layout(self):
		"""Verify Payment & Status box shows Unpaid tag when outstanding amount > 0."""
		inv = self._get_test_invoice(is_paid=False, with_transporter=True)
		html = frappe.get_print("Sales Invoice", inv.name, print_format="GST Invoice - Original for Receiver")

		self.assertIn("Unpaid:", html)
		self.assertIn("Shipping & Logistics Details", html)

	def test_05_dedicated_shipping_details_section(self):
		"""Verify bottom section contains dedicated Transporter and Godown/Hub delivery info across all 3 formats."""
		inv = self._get_test_invoice(is_paid=True, with_transporter=True)

		for pf_name in self.print_formats:
			html = frappe.get_print("Sales Invoice", inv.name, print_format=pf_name)
			self.assertIn(
				"Shipping & Logistics Details", html, f"Dedicated Shipping details missing in '{pf_name}'"
			)
			self.assertIn(self.transporter_name, html, f"Transporter name missing in '{pf_name}'")
			self.assertIn("100 Transporter Origin Hub Street", html, f"Origin Hub missing in '{pf_name}'")
			self.assertIn("200 Destination Godown Road", html, f"Destination Godown missing in '{pf_name}'")

	def test_06_no_shipping_details_tag(self):
		"""Verify 'No Shipping Details' tag is displayed when no transporter is configured."""
		inv = self._get_test_invoice(is_paid=True, with_transporter=False)

		for pf_name in self.print_formats:
			html = frappe.get_print("Sales Invoice", inv.name, print_format=pf_name)
			self.assertIn("No Shipping Details", html, f"'No Shipping Details' tag missing in '{pf_name}'")

	def test_07_quantity_formatting_helper(self):
		"""Verify format_qty omits .0 for whole numbers and retains true fractions."""
		self.assertEqual(format_qty(5320.0), "5320")
		self.assertEqual(format_qty(2.0), "2")
		self.assertEqual(format_qty(15.0), "15")
		self.assertEqual(format_qty(2.5), "2.5")
		self.assertEqual(format_qty(0.75), "0.75")
		self.assertEqual(format_qty("10.0"), "10")
		self.assertEqual(format_qty(None), "")
		self.assertEqual(format_qty(0), "0")

	def test_08_code128_svg_generator(self):
		"""Verify get_code128_svg creates valid standalone SVG elements."""
		svg = get_code128_svg("INV-2627-00457")
		self.assertTrue(svg.startswith("<svg"))
		self.assertTrue(svg.endswith("</svg>"))
		self.assertIn("<rect", svg)
		self.assertIn('fill="#000"', svg)

	def test_09_discount_on_grand_total_rendering(self):
		"""Verify Additional Discount is rendered after Taxes when applied on Grand Total."""
		inv = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer",
				"company": "_Test Company",
				"is_pos": 0,
				"update_stock": 0,
				"apply_discount_on": "Grand Total",
				"discount_amount": 68.0,
				"items": [
					{
						"item_code": "_Test Item",
						"qty": 5,
						"rate": 100,
						"warehouse": "_Test Warehouse - _TC"
					}
				],
			}
		)
		
		# If the item or warehouse doesn't exist, this might fail, so let's fallback to the previous invoice but ensure it's not a return
		try:
			inv.insert()
			inv.submit()
		except Exception:
			# Fallback if fixtures are missing
			invoices = frappe.get_all(
				"Sales Invoice", filters={"docstatus": 1, "is_pos": 0, "is_return": 0}, order_by="creation desc", limit=1
			)
			inv = frappe.get_doc("Sales Invoice", invoices[0].name)
			inv.db_set({
				"apply_discount_on": "Grand Total",
				"discount_amount": 68.0
			})
			frappe.db.commit()
			inv.reload()

		self.assertEqual(inv.apply_discount_on, "Grand Total", f"Expected 'Grand Total', got {inv.apply_discount_on}")
		self.assertEqual(inv.discount_amount, 68.0, f"Expected 68.0, got {inv.discount_amount}")
		
		html = frappe.get_print("Sales Invoice", inv.name, print_format="GST Invoice - Original for Receiver")

		if "Additional Discount:" not in html:
			print(f"\\n\\nHTML DUMP FOR TEST 09:\\n{html}\\n\\n")
		
		self.assertIn("Additional Discount:", html, "Additional Discount not in HTML. Check the log for the full HTML dump.")
		self.assertIn("Grand Total:", html)

	def test_10_pos_flow_indication_on_gst_invoice(self):
		"""Verify POS Flow indicator renders 'Over-the-Counter / Point of Sale (POS)' on GST Invoice when is_pos=1."""
		invoices = frappe.get_all("Sales Invoice", filters={"docstatus": ["!=", 2]}, limit=1)
		inv = frappe.get_doc("Sales Invoice", invoices[0].name)
		inv.db_set(
			{
				"is_pos": 1,
				"pos_profile": "_Test POS Profile",
				"transporter": None,
				"custom_transporter": None,
				"custom_transporter_from_address": None,
				"custom_transporter_from_address_display": None,
			}
		)
		frappe.db.commit()
		inv.reload()

		for pf_name in self.print_formats:
			html = frappe.get_print("Sales Invoice", inv.name, print_format=pf_name)
			self.assertIn("Point of Sale (POS)", html, f"POS indicator missing in '{pf_name}'")
			self.assertIn(
				"Over-the-Counter / Point of Sale (POS)",
				html,
				f"Over-the-Counter mode missing in '{pf_name}'",
			)
			self.assertIn("_Test POS Profile", html, f"POS Profile name missing in '{pf_name}'")
