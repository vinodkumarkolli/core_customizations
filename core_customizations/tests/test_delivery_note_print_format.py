import unittest

import frappe
from frappe.utils import nowtime, today

from core_customizations.tests.test_fixtures import ensure_test_fixtures


class TestDeliveryNotePrintFormat(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.flags.ignore_permissions = True
		# Ensure ERPNext master data exists in the blank CI environment
		ensure_test_fixtures()
		# Resolve company dynamically; CI site will have a different name
		cls.company = (
			frappe.db.get_value("Company", "Sravi Enterprises - Kolapakkam", "name")
			or "Sravi Enterprises - Kolapakkam"
		)
		cls.transporter_name = "_Test Speed Express Logistics"

		if not frappe.db.exists("Supplier", {"supplier_name": cls.transporter_name}):
			sup = frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": cls.transporter_name,
					"supplier_group": "Services",
					"is_transporter": 1,
				}
			).insert(ignore_permissions=True)
			cls.transporter_supplier = sup.name
		else:
			cls.transporter_supplier = frappe.db.get_value(
				"Supplier", {"supplier_name": cls.transporter_name}, "name"
			)
			frappe.db.set_value("Supplier", cls.transporter_supplier, "is_transporter", 1)

		# Ensure addresses exist
		cls.origin_address_name = cls._create_address(
			"_Test DN Origin Hub",
			cls.transporter_supplier,
			"100 Transporter Origin Hub Street",
			"Chennai",
			"Tamil Nadu",
			"600001",
			"33AAGCR8772D1Z9",
		)

		cls.godown_address_name = cls._create_address(
			"_Test DN Dest Godown",
			cls.transporter_supplier,
			"200 Destination Godown Road",
			"Salem",
			"Tamil Nadu",
			"636001",
			"33AAGCR8772D1Z9",
		)

		# Ensure test item exists
		cls.item_code_1 = "_Test DN Print Item 1"
		if not frappe.db.exists("Item", cls.item_code_1):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": cls.item_code_1,
					"item_name": "Deluxe LED Bulb 10W",
					"item_group": "All Item Groups",
					"gst_hsn_code": "30049011",
					"has_batch_no": 1,
					"create_new_batch": 0,
					"stock_uom": "Nos",
					"is_stock_item": 1,
				}
			).insert(ignore_permissions=True)
		else:
			frappe.db.set_value("Item", cls.item_code_1, {"is_stock_item": 1, "has_batch_no": 1})

		cls.item_code_2 = "_Test DN Print Item 2"
		if not frappe.db.exists("Item", cls.item_code_2):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": cls.item_code_2,
					"item_name": "Premium Smart Switch",
					"item_group": "All Item Groups",
					"gst_hsn_code": "30049011",
					"has_batch_no": 1,
					"create_new_batch": 0,
					"stock_uom": "Nos",
					"is_stock_item": 1,
				}
			).insert(ignore_permissions=True)
		else:
			frappe.db.set_value("Item", cls.item_code_2, {"is_stock_item": 1, "has_batch_no": 1})

		# Ensure batches exist
		for b_id, itm in [
			("BATCH-BULB-001", cls.item_code_1),
			("BATCH-A", cls.item_code_1),
			("BATCH-B", cls.item_code_2),
		]:
			if not frappe.db.exists("Batch", b_id):
				frappe.get_doc({"doctype": "Batch", "batch_id": b_id, "item": itm}).insert(
					ignore_permissions=True
				)

		# Ensure test customer exists
		cls.customer = "_Test DN Print Customer"
		if not frappe.db.exists("Customer", cls.customer):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": cls.customer,
					"customer_group": "Commercial",
					"territory": "Direct Customers",
					"default_price_list": "Standard Selling",
					"mobile_no": "9876543210",
				}
			).insert(ignore_permissions=True)

		cls.print_formats = [
			"Delivery Note - Original for Consignee",
			"Delivery Note - Duplicate for Transporter",
			"Delivery Note - Triplicate for Supplier",
		]

	@classmethod
	def _create_address(cls, title, supplier_name, line1, city, state, pincode, gstin=None):
		addr_name = frappe.db.get_value(
			"Dynamic Link",
			{"parenttype": "Address", "link_doctype": "Supplier", "link_name": supplier_name},
			"parent",
		)
		if addr_name and frappe.db.get_value("Address", addr_name, "address_title") == title:
			if gstin:
				frappe.db.set_value("Address", addr_name, "gstin", gstin)
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
				"gstin": gstin,
				"links": [{"link_doctype": "Supplier", "link_name": supplier_name}],
			}
		).insert(ignore_permissions=True)
		return addr.name

	def _create_test_dn(self, items=None, with_transporter=True):
		if not items:
			items = [
				{
					"item_code": self.item_code_1,
					"item_name": "Deluxe LED Bulb 10W",
					"qty": 50,
					"uom": "Nos",
					"rate": 120.0,
					"warehouse": "Stores - SE-K",
					"batch_no": "BATCH-BULB-001",
				}
			]

		dn = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"company": self.company,
				"customer": self.customer,
				"posting_date": today(),
				"posting_time": nowtime(),
				"po_no": "PO-TEST-DN-999",
				"items": items,
				"transporter": self.transporter_supplier if with_transporter else None,
				"custom_transporter_from_address": self.origin_address_name if with_transporter else None,
				"custom_transporter_from_address_display": "100 Transporter Origin Hub Street, Chennai, Tamil Nadu"
				if with_transporter
				else None,
				"custom_is_godown_delivery": 1 if with_transporter else 0,
				"custom_transporter_to_address": self.godown_address_name if with_transporter else None,
				"custom_transporter_to_address_display": "200 Destination Godown Road, Bengaluru, Karnataka"
				if with_transporter
				else None,
				"lr_no": "LR-DN-8888" if with_transporter else None,
				"lr_date": today() if with_transporter else None,
				"vehicle_no": "TN-01-AB-1234" if with_transporter else None,
				"custom_total_boxes": 3 if with_transporter else None,
			}
		)
		dn.flags.ignore_validate_update_after_submit = True
		dn.flags.ignore_mandatory = True
		dn.insert(ignore_permissions=True)
		return dn

	def test_01_delivery_note_print_formats_exist(self):
		"""Verify all 3 Delivery Note print formats exist with Jinja configuration."""
		for pf_name in self.print_formats:
			self.assertTrue(
				frappe.db.exists("Print Format", pf_name), f"Print Format '{pf_name}' does not exist in DB"
			)
			pf = frappe.get_doc("Print Format", pf_name)
			self.assertEqual(pf.doc_type, "Delivery Note")
			self.assertEqual(pf.custom_format, 1)
			self.assertEqual(pf.print_format_type, "Jinja")
			self.assertEqual(pf.font, "DM Sans")

	def test_02_company_branding_and_badges(self):
		"""Verify Delivery Note header renders document title, GSTIN, and distinct copy badges."""
		dn = self._create_test_dn(with_transporter=True)

		expected_badges = {
			"Delivery Note - Original for Consignee": "Original for Consignee",
			"Delivery Note - Duplicate for Transporter": "Duplicate for Transporter",
			"Delivery Note - Triplicate for Supplier": "Triplicate for Supplier",
		}

		for pf_name, badge_text in expected_badges.items():
			html = frappe.get_print("Delivery Note", dn.name, print_format=pf_name, no_letterhead=1)
			self.assertIn("DELIVERY NOTE", html, f"'DELIVERY NOTE' title missing in {pf_name}")
			self.assertIn(badge_text, html, f"Badge '{badge_text}' missing in {pf_name}")
			self.assertIn(self.company, html, f"Company name missing in {pf_name}")
			self.assertIn(self.customer, html, f"Customer name missing in {pf_name}")
			self.assertIn("PO-TEST-DN-999", html, f"Customer PO No missing in {pf_name}")

	def test_03_logistics_and_shipping_details(self):
		"""Verify 3-column section renders Consignor, Consignee, Delivery & Logistics with Transporter, Origin, Godown, and LR details."""
		dn = self._create_test_dn(with_transporter=True)
		html = frappe.get_print(
			"Delivery Note", dn.name, print_format="Delivery Note - Original for Consignee", no_letterhead=1
		)

		self.assertIn("Consignor (Dispatch From)", html, "Consignor column header missing")
		self.assertIn("Consignee (Customer)", html, "Consignee column header missing")
		self.assertIn("Delivery & Logistics", html, "Delivery & Logistics column header missing")
		self.assertIn(self.transporter_name, html, "Transporter supplier name missing")
		self.assertIn("LR-DN-8888", html, "LR No missing")
		self.assertIn("TN-01-AB-1234", html, "Vehicle No missing")
		self.assertIn("3", html, "Total boxes missing")

	def test_04_submitted_single_item_packing_slips_mapped_to_items(self):
		"""Verify only SUBMITTED single-item Packing Slips map Box numbers to respective items."""
		dn = self._create_test_dn(
			items=[
				{
					"item_code": self.item_code_1,
					"item_name": "Deluxe LED Bulb 10W",
					"qty": 40,
					"uom": "Nos",
					"warehouse": "Stores - SE-K",
					"batch_no": "BATCH-BULB-001",
				}
			],
			with_transporter=True,
		)

		# Create submitted Packing Slip 1 (Box #1)
		ps1 = frappe.get_doc(
			{
				"doctype": "Packing Slip",
				"delivery_note": dn.name,
				"from_case_no": 1,
				"to_case_no": 1,
				"items": [
					{
						"item_code": self.item_code_1,
						"item_name": "Deluxe LED Bulb 10W",
						"batch_no": "BATCH-BULB-001",
						"qty": 20,
						"stock_uom": "Nos",
						"dn_detail": dn.items[0].name,
					}
				],
			}
		).insert(ignore_permissions=True)
		ps1.submit()

		# Create submitted Packing Slip 2 (Box #2)
		ps2 = frappe.get_doc(
			{
				"doctype": "Packing Slip",
				"delivery_note": dn.name,
				"from_case_no": 2,
				"to_case_no": 2,
				"items": [
					{
						"item_code": self.item_code_1,
						"item_name": "Deluxe LED Bulb 10W",
						"batch_no": "BATCH-BULB-001",
						"qty": 20,
						"stock_uom": "Nos",
						"dn_detail": dn.items[0].name,
					}
				],
			}
		).insert(ignore_permissions=True)
		ps2.submit()

		html = frappe.get_print(
			"Delivery Note", dn.name, print_format="Delivery Note - Original for Consignee", no_letterhead=1
		)

		self.assertIn("Box #1", html, "Box #1 missing from item allocation")
		self.assertIn("Box #2", html, "Box #2 missing from item allocation")
		self.assertIn("20 Nos", html, "Box quantity missing from item allocation")
		self.assertIn(ps1.name, html, "Packing Slip 1 ID missing from item allocation")
		self.assertIn(ps2.name, html, "Packing Slip 2 ID missing from item allocation")

	def test_05_draft_packing_slips_ignored_in_delivery_note_print(self):
		"""Verify DRAFT (docstatus=0) Packing Slips are NOT mapped to the Delivery Note print format."""
		dn = self._create_test_dn(
			items=[
				{
					"item_code": self.item_code_1,
					"item_name": "Deluxe LED Bulb 10W",
					"qty": 50,
					"uom": "Nos",
					"warehouse": "Stores - SE-K",
				}
			],
			with_transporter=True,
		)

		# Create DRAFT Packing Slip 99 (Do NOT submit)
		ps_draft = frappe.get_doc(
			{
				"doctype": "Packing Slip",
				"delivery_note": dn.name,
				"from_case_no": 99,
				"to_case_no": 99,
				"items": [
					{
						"item_code": self.item_code_1,
						"item_name": "Deluxe LED Bulb 10W",
						"qty": 50,
						"stock_uom": "Nos",
						"dn_detail": dn.items[0].name,
					}
				],
			}
		).insert(ignore_permissions=True)

		self.assertEqual(ps_draft.docstatus, 0)

		html = frappe.get_print(
			"Delivery Note", dn.name, print_format="Delivery Note - Original for Consignee", no_letterhead=1
		)

		self.assertNotIn(
			"Box #99", html, "Draft Packing Slip Box #99 should NOT appear on Delivery Note print format"
		)

	def test_06_mixed_packing_slips_consolidation_row(self):
		"""Verify SUBMITTED Mixed Packing Slips render in the Consolidated Packages section."""
		dn = self._create_test_dn(
			items=[
				{
					"item_code": self.item_code_1,
					"item_name": "Deluxe LED Bulb 10W",
					"qty": 10,
					"uom": "Nos",
					"warehouse": "Stores - SE-K",
					"batch_no": "BATCH-A",
				},
				{
					"item_code": self.item_code_2,
					"item_name": "Premium Smart Switch",
					"qty": 15,
					"uom": "Nos",
					"warehouse": "Stores - SE-K",
					"batch_no": "BATCH-B",
				},
			],
			with_transporter=True,
		)

		# Create submitted Mixed Packing Slip (Box #3)
		ps_mixed = frappe.get_doc(
			{
				"doctype": "Packing Slip",
				"delivery_note": dn.name,
				"from_case_no": 3,
				"to_case_no": 3,
				"items": [
					{
						"item_code": self.item_code_1,
						"item_name": "Deluxe LED Bulb 10W",
						"batch_no": "BATCH-A",
						"qty": 10,
						"stock_uom": "Nos",
						"dn_detail": dn.items[0].name,
					},
					{
						"item_code": self.item_code_2,
						"item_name": "Premium Smart Switch",
						"batch_no": "BATCH-B",
						"qty": 15,
						"stock_uom": "Nos",
						"dn_detail": dn.items[1].name,
					},
				],
			}
		).insert(ignore_permissions=True)
		ps_mixed.submit()

		html = frappe.get_print(
			"Delivery Note", dn.name, print_format="Delivery Note - Original for Consignee", no_letterhead=1
		)

		self.assertIn("Consolidated / Mixed Item Packages", html, "Mixed packages header missing")
		self.assertIn("Box #3", html, "Mixed Box #3 label missing")
		self.assertIn("Deluxe LED Bulb 10W", html, "Item 1 in mixed carton missing")
		self.assertIn("Premium Smart Switch", html, "Item 2 in mixed carton missing")
		self.assertIn("BATCH-A", html, "Batch A in mixed carton missing")
		self.assertIn("BATCH-B", html, "Batch B in mixed carton missing")

	def test_07_financial_information_omitted(self):
		"""Verify financial/rate/discount information is omitted from Delivery Note print formats."""
		dn = self._create_test_dn(with_transporter=True)
		html = frappe.get_print(
			"Delivery Note", dn.name, print_format="Delivery Note - Original for Consignee", no_letterhead=1
		)

		self.assertNotIn("List Rate", html, "Financial 'List Rate' should be omitted")
		self.assertNotIn("Taxable Amount", html, "Financial 'Taxable Amount' should be omitted")
		self.assertNotIn("Discount %", html, "Financial 'Discount %' should be omitted")
		self.assertNotIn("Grand Total:", html, "Financial 'Grand Total:' should be omitted")

	def test_08_dual_stamp_signature_boxes_and_audit_footer(self):
		"""Verify Receiver's Acknowledgement, Authorised Signatory stamp boxes, Generated By and On footers."""
		dn = self._create_test_dn(with_transporter=True)
		html = frappe.get_print(
			"Delivery Note", dn.name, print_format="Delivery Note - Original for Consignee", no_letterhead=1
		)

		self.assertIn("Receiver's Acknowledgement:", html, "Receiver's Acknowledgement section missing")
		self.assertIn("[ Receiver's Signature & Company Stamp ]", html, "Receiver Stamp placeholder missing")
		self.assertIn(
			"[ Authorised Signatory & Stamp ]", html, "Authorised Signatory Stamp placeholder missing"
		)
		self.assertIn("Authorised Signatory", html, "Authorised Signatory label missing")
		self.assertIn("Generated By:", html, "Generated By footer missing")
		self.assertIn("Generated On:", html, "Generated On footer missing")

	def test_09_company_shipping_address_rendered_in_consignor_column(self):
		"""Verify Delivery Note renders company's dispatch/shipping address in the Consignor (Dispatch From) column."""
		dn = self._create_test_dn(with_transporter=True)
		dn.dispatch_address_name = self.origin_address_name
		dn.dispatch_address = "100 Transporter Origin Hub Street<br>Chennai<br>Tamil Nadu"
		dn.db_update()

		html = frappe.get_print(
			"Delivery Note", dn.name, print_format="Delivery Note - Original for Consignee", no_letterhead=1
		)
		self.assertIn("Consignor (Dispatch From)", html, "Consignor header missing")
		self.assertIn(
			"100 Transporter Origin Hub Street",
			html,
			"Company dispatch/shipping address should be rendered in Consignor column",
		)

	def test_10_warehouse_address_rendered_in_consignor_column(self):
		"""Verify Delivery Note renders warehouse address in the Consignor column if warehouse has address configured."""
		dn = self._create_test_dn(with_transporter=True)
		dn.set_warehouse = "Coimbatore Goodown - SE-K"
		for itm in dn.items:
			itm.warehouse = "Coimbatore Goodown - SE-K"
		dn.dispatch_address_name = frappe.db.get_value(
			"Dynamic Link", 
			{"link_doctype": "Warehouse", "link_name": "Coimbatore Goodown - SE-K", "parenttype": "Address"}, 
			"parent"
		)
		dn.dispatch_address = frappe.db.get_value("Address", dn.dispatch_address_name, "address_line1")
		dn.save(ignore_permissions=True)
		
		self.assertTrue(dn.dispatch_address_name, "dispatch_address_name is None after save")
		address = frappe.get_doc("Address", dn.dispatch_address_name)
		self.assertIn("6/57", address.address_line1 or "", f"Expected address line 1 to contain 6/57, got {address.address_line1}")

		html = frappe.get_print(
			"Delivery Note", dn.name, print_format="Delivery Note - Original for Consignee", no_letterhead=1
		)
		self.assertIn(
			"6/57, MALAI Samy Kovil Street, Madukkarai",
			html,
			f"Warehouse address line 1 missing in Consignor column. HTML: {html[:200]}...",
		)
		self.assertIn("Coimbatore", html, "Warehouse city missing in Consignor column")
		self.assertIn("8056496441", html, "Warehouse phone missing in Consignor column")

	def test_11_customer_shipping_address_rendered_in_consignee_column(self):
		"""Verify Delivery Note renders Customer's Shipping Address in the Consignee column over Billing Address."""
		dn = self._create_test_dn(with_transporter=True)
		dn.address_display = "123 Billing Road, Financial Center, Chennai"
		dn.shipping_address = "999 Factory Warehouse Delivery Gate, Industrial Estate, Salem"
		dn.db_update()

		html = frappe.get_print(
			"Delivery Note", dn.name, print_format="Delivery Note - Original for Consignee", no_letterhead=1
		)
		self.assertIn("Consignee (Customer)", html, "Consignee header missing")
		self.assertIn(
			"999 Factory Warehouse Delivery Gate",
			html,
			"Customer Shipping Address should be rendered in Consignee column",
		)
