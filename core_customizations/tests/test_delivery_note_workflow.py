# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate, nowtime

from core_customizations.core_customizations.delivery_note import (
	_get_formatted_address,
	delete_packing_slips,
	generate_packing_slips,
	get_bulk_packing_labels_html,
	get_lr_dialog_info,
	get_packing_slips_list,
	get_unpacked_items_summary,
	submit_packing_slips,
	update_lr_details,
	update_transporter_details,
)
from core_customizations.core_customizations.sales_invoice import validate_delivery_note_mandatory
from core_customizations.tests.test_fixtures import ensure_test_fixtures


class TestDeliveryNoteWorkflow(IntegrationTestCase):
	"""
	Comprehensive integration test suite for 3PL Delivery Note Transporter Assignment,
	Address Sanitization & GSTIN Display, Packing Slip Generator with dn_detail,
	Manage Packing Slips with stock_uom, 4x6 Thermal Label Printing (Single & Bulk),
	Godown Delivery toggle clearing, and Mandatory Delivery Note Validation on Sales Invoice.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Ensure ERPNext master data exists in the blank CI environment
		ensure_test_fixtures()

		# 1. Create a Test Customer with default transporter settings
		cls.customer_name = "_Test 3PL Customer"
		if not frappe.db.exists("Customer", cls.customer_name):
			cust = frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": cls.customer_name,
					"customer_group": "Commercial",
					"territory": "All Territories",
					"default_price_list": "Standard Selling",
				}
			).insert(ignore_permissions=True)
		else:
			cust = frappe.get_doc("Customer", cls.customer_name)

		# 2. Create Transporter Supplier
		cls.transporter_name = "_Test 3PL Transporter"
		if not frappe.db.exists("Supplier", cls.transporter_name):
			supp = frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": cls.transporter_name,
					"supplier_group": "Services",
					"is_transporter": 1,
				}
			).insert(ignore_permissions=True)
		else:
			supp = frappe.get_doc("Supplier", cls.transporter_name)
			if not supp.is_transporter:
				supp.is_transporter = 1
				supp.save(ignore_permissions=True)

		# 3. Create Addresses with GSTIN
		cls.from_address = cls._create_address(
			"_Test Origin Parrys Hub",
			cls.transporter_name,
			"100 Wall Tax Road, Parrys",
			"Chennai",
			"Tamil Nadu",
			"600001",
			gstin="33AAGCR8772D1Z9",
		)
		cls.to_address = cls._create_address(
			"_Test Dest Salem Godown",
			cls.transporter_name,
			"500 Godown Main Road",
			"Salem",
			"Tamil Nadu",
			"636001",
			gstin="33AAGCR8772D1Z9",
		)

		# Set defaults on Customer
		cust.custom_default_transporter = cls.transporter_name
		cust.custom_default_transporter_from_address = cls.from_address
		cust.custom_is_godown_delivery = 1
		cust.custom_default_transporter_to_address = cls.to_address
		cust.save(ignore_permissions=True)

		# 4. Create Test Items
		cls.item_code = "_Test_3PL_Carton_Item"
		if not frappe.db.exists("Item", cls.item_code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": cls.item_code,
					"item_name": "Test 3PL Carton Item",
					"item_group": "Products",
					"stock_uom": "Nos",
					"is_stock_item": 0,
					"gst_hsn_code": "30049011",
				}
			).insert(ignore_permissions=True)

		cls.item_code_2 = "_Test_3PL_Loose_Item"
		if not frappe.db.exists("Item", cls.item_code_2):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": cls.item_code_2,
					"item_name": "Test 3PL Loose Item",
					"item_group": "Products",
					"stock_uom": "Nos",
					"is_stock_item": 0,
					"gst_hsn_code": "30049011",
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

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

	def _create_test_delivery_note(self):
		company = "Sravi Enterprises - Kolapakkam"
		dn = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"customer": self.customer_name,
				"company": company,
				"items": [
					{
						"item_code": self.item_code,
						"qty": 500,
						"uom": "Nos",
					},
					{
						"item_code": self.item_code_2,
						"qty": 100,
						"uom": "Nos",
					},
				],
			}
		).insert(ignore_permissions=True)
		return dn

	def test_01_update_transporter_details_godown_enabled(self):
		"""Verify updating transporter details with Godown Delivery enabled."""
		dn = self._create_test_delivery_note()

		res = update_transporter_details(
			delivery_note=dn.name,
			transporter=self.transporter_name,
			from_address=self.from_address,
			is_godown=1,
			to_address=self.to_address,
		)

		self.assertEqual(res["transporter"], self.transporter_name)
		self.assertEqual(res["is_godown_delivery"], 1)
		self.assertEqual(res["to_address"], self.to_address)
		self.assertIn("GSTIN: 33AAGCR8772D1Z9", res["to_address_display"])
		self.assertNotIn("<br>", res["to_address_display"])

		dn.reload()
		self.assertEqual(dn.transporter, self.transporter_name)
		self.assertEqual(dn.custom_is_godown_delivery, 1)
		self.assertEqual(dn.custom_transporter_to_address, self.to_address)
		self.assertIn("GSTIN: 33AAGCR8772D1Z9", dn.custom_transporter_to_address_display)

	def test_02_update_transporter_details_godown_disabled_clears_destination(self):
		"""Verify unchecking Godown Delivery clears to_address and to_address_display."""
		dn = self._create_test_delivery_note()

		# First set as Godown
		update_transporter_details(
			delivery_note=dn.name,
			transporter=self.transporter_name,
			from_address=self.from_address,
			is_godown=1,
			to_address=self.to_address,
		)

		# Now update as Door Delivery (is_godown = 0)
		res = update_transporter_details(
			delivery_note=dn.name,
			transporter=self.transporter_name,
			from_address=self.from_address,
			is_godown=0,
			to_address=None,
		)

		self.assertEqual(res["is_godown_delivery"], 0)
		self.assertIsNone(res["to_address"])
		self.assertEqual(res["to_address_display"], "")

		dn.reload()
		self.assertEqual(dn.custom_is_godown_delivery, 0)
		self.assertIsNone(dn.custom_transporter_to_address)
		self.assertEqual(dn.custom_transporter_to_address_display or "", "")

	def test_03_address_formatting_strips_html_and_includes_gstin(self):
		"""Verify _get_formatted_address strips all HTML tags and guarantees GSTIN."""
		formatted = _get_formatted_address(self.from_address)
		self.assertNotIn("<br>", formatted)
		self.assertNotIn("<br/>", formatted)
		self.assertNotIn("<", formatted)
		self.assertIn("GSTIN: 33AAGCR8772D1Z9", formatted)
		self.assertIn("100 Wall Tax Road, Parrys", formatted)

	def test_04_update_lr_details_api(self):
		"""Verify updating LR details, vehicle number, S3 image, and syncing with linked Sales Invoice."""
		dn = self._create_test_delivery_note()

		# 1. Before Sales Invoice: get_lr_dialog_info indicates has_sales_invoice = False
		info_before = get_lr_dialog_info(dn.name)
		self.assertFalse(info_before["has_sales_invoice"])

		# 2. Create linked Sales Invoice
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": dn.company,
				"customer": self.customer_name,
				"update_stock": 0,
				"items": [
					{
						"item_code": self.item_code,
						"qty": 500,
						"rate": 100,
						"delivery_note": dn.name,
						"dn_detail": dn.items[0].name,
					}
				],
			}
		)
		si.flags.ignore_mandatory = True
		si.insert(ignore_permissions=True)

		# 3. After Sales Invoice: get_lr_dialog_info indicates has_sales_invoice = True and threshold checked
		info_after = get_lr_dialog_info(dn.name)
		self.assertTrue(info_after["has_sales_invoice"])
		self.assertEqual(len(info_after["sales_invoices"]), 1)

		# 4. Update LR Details with vehicle_no, mode_of_transport, and S3 image attachment
		res = update_lr_details(
			delivery_note=dn.name,
			lr_no="LR-CHENNAI-9988",
			lr_date="2026-08-23",
			vehicle_no="tn 28 ab 1234",
			mode_of_transport="Road",
			gst_vehicle_type="Regular",
			lr_receipt_image="/files/sample_lr_slip.png",
		)
		self.assertEqual(res["lr_no"], "LR-CHENNAI-9988")
		self.assertEqual(res["vehicle_no"], "TN28AB1234")
		self.assertEqual(res["lr_receipt_image"], "/files/sample_lr_slip.png")
		self.assertIn(si.name, res["synced_invoices"])

		# 5. Verify Delivery Note updated
		dn.reload()
		self.assertEqual(dn.lr_no, "LR-CHENNAI-9988")
		self.assertEqual(str(dn.lr_date), "2026-08-23")
		self.assertEqual(dn.vehicle_no, "TN28AB1234")
		self.assertEqual(dn.mode_of_transport, "Road")
		self.assertEqual(dn.gst_vehicle_type, "Regular")
		self.assertEqual(dn.custom_lr_receipt_image, "/files/sample_lr_slip.png")

		# 6. Verify linked Sales Invoice synchronized
		si.reload()
		self.assertEqual(si.lr_no, "LR-CHENNAI-9988")
		self.assertEqual(str(si.lr_date), "2026-08-23")
		self.assertEqual(si.vehicle_no, "TN28AB1234")
		self.assertEqual(si.mode_of_transport, "Road")
		self.assertEqual(si.gst_vehicle_type, "Regular")
		self.assertEqual(si.custom_lr_receipt_image, "/files/sample_lr_slip.png")

	def test_05_packing_slip_generator_single_and_mixed(self):
		"""Verify generating sequential packing slips with valid dn_detail references."""
		dn = self._create_test_delivery_note()

		# Generate 2 boxes of 200 units each for item 1 -> Box 1 and Box 2
		res1 = generate_packing_slips(
			delivery_note=dn.name,
			packing_type="single",
			item_code=self.item_code,
			qty_per_box=200,
			no_of_boxes=2,
		)
		self.assertEqual(len(res1["created_packing_slips"]), 2)
		self.assertEqual(res1["total_boxes"], 2)

		# Verify Packing Slip item has dn_detail set
		ps1 = frappe.get_doc("Packing Slip", res1["created_packing_slips"][0])
		self.assertEqual(ps1.items[0].dn_detail, dn.items[0].name)
		self.assertEqual(ps1.from_case_no, 1)

		# Generate 1 mixed carton with remainder of item 1 (100) and item 2 (100) -> Box 3
		res2 = generate_packing_slips(
			delivery_note=dn.name,
			packing_type="mixed",
			mixed_items=[
				{"item_code": self.item_code, "qty": 100},
				{"item_code": self.item_code_2, "qty": 100},
			],
			no_of_boxes=1,
		)
		self.assertEqual(len(res2["created_packing_slips"]), 1)
		self.assertEqual(res2["total_boxes"], 3)

		# Verify summary shows 0 balance for both items
		summary = get_unpacked_items_summary(dn.name)
		self.assertEqual(summary["total_boxes_created"], 3)
		self.assertEqual(summary["next_package_no"], 4)

		item1_sum = next(i for i in summary["items"] if i["item_code"] == self.item_code)
		item2_sum = next(i for i in summary["items"] if i["item_code"] == self.item_code_2)

		self.assertEqual(item1_sum["packed_qty"], 500.0)
		self.assertEqual(item1_sum["remaining_qty"], 0.0)
		self.assertEqual(item2_sum["packed_qty"], 100.0)
		self.assertEqual(item2_sum["remaining_qty"], 0.0)

	def test_06_manage_and_delete_packing_slips(self):
		"""Verify listing packing slips with stock_uom and deleting them."""
		dn = self._create_test_delivery_note()

		generate_packing_slips(
			delivery_note=dn.name,
			packing_type="single",
			item_code=self.item_code,
			qty_per_box=250,
			no_of_boxes=2,
		)

		slips = get_packing_slips_list(dn.name)
		self.assertEqual(len(slips), 2)
		self.assertEqual(slips[0]["from_case_no"], 1)
		self.assertEqual(slips[1]["from_case_no"], 2)
		self.assertIn("Nos", slips[0]["items_display"])

		# Delete single slip
		del_res = delete_packing_slips(dn.name, packing_slip_names=[slips[0]["name"]])
		self.assertEqual(del_res["deleted_count"], 1)
		self.assertEqual(del_res["remaining_count"], 1)

		# Delete remaining slips
		del_res_all = delete_packing_slips(dn.name)
		self.assertEqual(del_res_all["remaining_count"], 0)

	def test_07_bulk_and_single_4x6_thermal_label_rendering(self):
		"""Verify Carton Shipping Label (4x6) single and bulk render without letterhead error."""
		dn = self._create_test_delivery_note()
		update_transporter_details(
			delivery_note=dn.name,
			transporter=self.transporter_name,
			from_address=self.from_address,
			is_godown=1,
			to_address=self.to_address,
		)

		gen_res = generate_packing_slips(
			delivery_note=dn.name,
			packing_type="single",
			item_code=self.item_code,
			qty_per_box=250,
			no_of_boxes=2,
		)
		ps_name = gen_res["created_packing_slips"][0]

		# 1. Test single print format
		html = frappe.get_print(
			"Packing Slip", ps_name, print_format="Carton Shipping Label (4x6)", no_letterhead=1
		)
		self.assertIn(ps_name, html)
		self.assertIn(dn.name, html)
		self.assertIn("BOX NUMBER / TOTAL", html)
		self.assertIn("BOX [ &nbsp;<b>1</b>&nbsp; ]", html)
		self.assertIn("GODOWN PICKUP", html)
		self.assertIn("GSTIN: 33AAGCR8772D1Z9", html)

		# 2. Bulk print strictly skips drafts, so calling now throws error
		self.assertRaises(frappe.ValidationError, get_bulk_packing_labels_html, dn.name)

		# 3. Submit slips and test bulk print HTML again
		submit_packing_slips(dn.name, packing_slip_names=json.dumps(gen_res["created_packing_slips"]))
		bulk_html = get_bulk_packing_labels_html(dn.name)
		self.assertIn(gen_res["created_packing_slips"][0], bulk_html)
		self.assertIn(gen_res["created_packing_slips"][1], bulk_html)
		self.assertIn("page-break", bulk_html)

	def test_08_mandatory_delivery_note_on_sales_invoice(self):
		"""Verify Sales Invoice creation without a Delivery Note raises a validation error."""
		company = "Sravi Enterprises - Kolapakkam"

		# Direct Sales Invoice without Delivery Note should fail
		direct_inv = frappe.new_doc("Sales Invoice")
		direct_inv.customer = self.customer_name
		direct_inv.company = company
		direct_inv.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": 10,
				"rate": 100,
				"delivery_note": None,
			},
		)

		self.assertRaises(frappe.ValidationError, validate_delivery_note_mandatory, direct_inv)

		# Sales Invoice linked to a Delivery Note should succeed
		dn = self._create_test_delivery_note()
		valid_inv = frappe.new_doc("Sales Invoice")
		valid_inv.customer = self.customer_name
		valid_inv.company = company
		valid_inv.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": 10,
				"rate": 100,
				"delivery_note": dn.name,
			},
		)

		# Should not raise exception
		validate_delivery_note_mandatory(valid_inv)

	def test_09_godown_delivery_validation_fails_without_to_address(self):
		"""Verify update_transporter_details raises ValidationError if is_godown=1 but to_address is empty."""
		dn = self._create_test_delivery_note()

		with self.assertRaises(frappe.ValidationError):
			update_transporter_details(
				delivery_note=dn.name,
				transporter=self.transporter_name,
				from_address=self.from_address,
				is_godown=1,
				to_address=None,
			)

	def test_10_godown_delivery_validation_fails_without_from_address(self):
		"""Verify update_transporter_details raises ValidationError if is_godown=1 but from_address is empty."""
		dn = self._create_test_delivery_note()

		with self.assertRaises(frappe.ValidationError):
			update_transporter_details(
				delivery_note=dn.name,
				transporter=self.transporter_name,
				from_address=None,
				is_godown=1,
				to_address=self.to_address,
			)

	def test_11_customer_transporter_defaults_fetched_on_demand(self):
		"""Verify new Delivery Note starts without transporter until explicitly assigned or fetched on demand."""
		dn = self._create_test_delivery_note()
		dn.reload()

		# Initial document is blank for transporter
		self.assertIsNone(dn.transporter)
		self.assertIsNone(dn.custom_transporter_from_address)

		# Customer master defaults are available via summary API for popup "Fetch Customer Defaults"
		summary = get_unpacked_items_summary(dn.name)
		self.assertEqual(summary["customer_defaults"]["default_transporter"], self.transporter_name)
		self.assertEqual(summary["customer_defaults"]["default_from_address"], self.from_address)
		self.assertEqual(summary["customer_defaults"]["default_is_godown"], 1)
		self.assertEqual(summary["customer_defaults"]["default_to_address"], self.to_address)

		# When user applies the customer defaults via update_transporter_details
		update_transporter_details(
			delivery_note=dn.name,
			transporter=summary["customer_defaults"]["default_transporter"],
			from_address=summary["customer_defaults"]["default_from_address"],
			is_godown=summary["customer_defaults"]["default_is_godown"],
			to_address=summary["customer_defaults"]["default_to_address"],
		)
		dn.reload()

		self.assertEqual(dn.transporter, self.transporter_name)
		self.assertEqual(dn.custom_transporter_from_address, self.from_address)
		self.assertEqual(dn.custom_is_godown_delivery, 1)
		self.assertEqual(dn.custom_transporter_to_address, self.to_address)
		self.assertIn("GSTIN: 33AAGCR8772D1Z9", dn.custom_transporter_from_address_display)
		self.assertIn("GSTIN: 33AAGCR8772D1Z9", dn.custom_transporter_to_address_display)
		self.assertNotIn("<br>", dn.custom_transporter_from_address_display)
		self.assertNotIn("<br>", dn.custom_transporter_to_address_display)

	def test_12_delivery_note_submission_auto_submits_draft_packing_slips(self):
		"""Verify submitting Delivery Note automatically submits all linked Draft Packing Slips."""
		dn = self._create_test_delivery_note()

		gen_res = generate_packing_slips(
			delivery_note=dn.name,
			packing_type="single",
			item_code=self.item_code,
			qty_per_box=250,
			no_of_boxes=2,
		)
		ps_names = gen_res["created_packing_slips"]

		# Assert they are initially in Draft (docstatus: 0)
		for ps_name in ps_names:
			self.assertEqual(frappe.db.get_value("Packing Slip", ps_name, "docstatus"), 0)

		# Submit Delivery Note
		dn.reload()
		dn.submit()

		# Assert all linked Packing Slips are now Submitted (docstatus: 1)
		for ps_name in ps_names:
			self.assertEqual(frappe.db.get_value("Packing Slip", ps_name, "docstatus"), 1)

	def test_13_delivery_note_cancellation_auto_cancels_submitted_packing_slips(self):
		"""Verify cancelling Delivery Note automatically cancels all linked Submitted Packing Slips."""
		dn = self._create_test_delivery_note()

		gen_res = generate_packing_slips(
			delivery_note=dn.name,
			packing_type="single",
			item_code=self.item_code,
			qty_per_box=250,
			no_of_boxes=2,
		)
		ps_names = gen_res["created_packing_slips"]

		# Submit Delivery Note (which submits packing slips)
		dn.reload()
		dn.submit()

		# Cancel Delivery Note
		dn.reload()
		dn.cancel()

		# Assert all linked Packing Slips are now Cancelled (docstatus: 2)
		for ps_name in ps_names:
			self.assertEqual(frappe.db.get_value("Packing Slip", ps_name, "docstatus"), 2)

	def test_14_sales_invoice_from_delivery_note_disallows_update_stock(self):
		"""Verify Sales Invoice linked to a Delivery Note blocks update_stock = 1."""
		company = "Sravi Enterprises - Kolapakkam"
		dn = self._create_test_delivery_note()

		inv = frappe.new_doc("Sales Invoice")
		inv.customer = self.customer_name
		inv.company = company
		inv.update_stock = 1
		inv.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": 10,
				"rate": 100,
				"delivery_note": dn.name,
			},
		)

		# Should raise validation error because update_stock cannot be 1 when linked to DN
		self.assertRaises(frappe.ValidationError, validate_delivery_note_mandatory, inv)

		# When update_stock is 0, validation should succeed
		inv.update_stock = 0
		validate_delivery_note_mandatory(inv)

	def test_15_batch_allocation_on_delivery_note_via_monkey_patch(self):
		"""Verify monkey patch custom_update_stock triggers batch allocation for Delivery Note."""
		from core_customizations.monkey_patches import custom_update_stock

		# Create a batched item for testing if not present
		batch_item_code = "_Test_3PL_Batched_Item"
		if not frappe.db.exists("Item", batch_item_code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": batch_item_code,
					"item_name": "Test 3PL Batched Item",
					"item_group": "Products",
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"has_batch_no": 1,
					"create_new_batch": 1,
					"gst_hsn_code": "30049011",
				}
			).insert(ignore_permissions=True)

		ctx = frappe._dict(
			{
				"doctype": "Delivery Note",
				"item_code": batch_item_code,
				"warehouse": "Stores - SE-K",
				"child_docname": "dn_detail_1",
			}
		)
		out = frappe._dict(
			{
				"warehouse": "Stores - SE-K",
				"stock_qty": 5,
				"uom": "Nos",
				"item_code": batch_item_code,
				"has_batch_no": 1,
				"has_serial_no": 0,
			}
		)

		# Calling custom_update_stock should execute without error for Delivery Note
		custom_update_stock(ctx, out)
		# Verify out has warehouse preserved
		self.assertEqual(out.warehouse, "Stores - SE-K")

	def test_16_sales_invoice_without_update_stock_does_not_trigger_batch_selection(self):
		"""Verify monkey patch custom_update_stock skips Sales Invoice when update_stock is 0."""
		from core_customizations.monkey_patches import custom_update_stock

		ctx = frappe._dict(
			{
				"doctype": "Sales Invoice",
				"update_stock": 0,
				"item_code": self.item_code,
				"warehouse": "Stores - SE-K",
			}
		)
		out = frappe._dict(
			{
				"warehouse": "Stores - SE-K",
				"stock_qty": 5,
				"uom": "Nos",
				"item_code": self.item_code,
				"has_batch_no": 1,
				"has_serial_no": 0,
			}
		)

		# For Sales Invoice without update_stock, batch allocation in custom_update_stock is bypassed
		custom_update_stock(ctx, out)
		self.assertNotIn("batch_no", out)

	def test_17_delivery_note_overridden_transporter_takes_precedence_over_customer_defaults(self):
		"""Verify Delivery Note specific transporter override takes precedence over Customer Master defaults."""
		# 1. Create an alternate transporter and hub
		alt_transporter_name = "_Test Alternate Transporter"
		if not frappe.db.exists("Supplier", alt_transporter_name):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": alt_transporter_name,
					"supplier_group": "Services",
					"is_transporter": 1,
				}
			).insert(ignore_permissions=True)

		alt_hub_address = self._create_address(
			"_Test Alt Koyambedu Hub",
			alt_transporter_name,
			"500 Koyambedu Wholesale Market Road",
			"Chennai",
			"Tamil Nadu",
			"600107",
			gstin="33AAGCR8772D1Z9",
		)

		company = "Sravi Enterprises - Kolapakkam"

		# 2. Create a Delivery Note explicitly with the alternate transporter & Door Delivery (is_godown = 0)
		dn = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"customer": self.customer_name,
				"company": company,
				"transporter": alt_transporter_name,
				"custom_transporter_from_address": alt_hub_address,
				"custom_is_godown_delivery": 0,
				"custom_transporter_to_address": None,
				"items": [
					{
						"item_code": self.item_code,
						"qty": 100,
						"uom": "Nos",
					}
				],
			}
		).insert(ignore_permissions=True)

		dn.reload()

		# Assert Delivery Note preserved its explicit override (NOT replaced with customer default transporter)
		self.assertEqual(dn.transporter, alt_transporter_name)
		self.assertEqual(dn.custom_transporter_from_address, alt_hub_address)
		self.assertEqual(dn.custom_is_godown_delivery, 0)
		self.assertIsNone(dn.custom_transporter_to_address)
		self.assertIn("500 Koyambedu Wholesale Market Road", dn.custom_transporter_from_address_display)

		# 3. Verify API returns the Delivery Note's specific override in current_transporter
		summary = get_unpacked_items_summary(dn.name)
		self.assertEqual(summary["current_transporter"]["transporter"], alt_transporter_name)
		self.assertEqual(summary["current_transporter"]["from_address"], alt_hub_address)
		self.assertEqual(summary["current_transporter"]["is_godown_delivery"], 0)
		self.assertIsNone(summary["current_transporter"]["to_address"])

		# And still provides customer master defaults for reference if the user wants to switch back
		self.assertEqual(summary["customer_defaults"]["default_transporter"], self.transporter_name)
		self.assertEqual(summary["customer_defaults"]["default_from_address"], self.from_address)
		self.assertEqual(summary["customer_defaults"]["default_is_godown"], 1)
		self.assertEqual(summary["customer_defaults"]["default_to_address"], self.to_address)

	def test_18_submit_draft_packing_slips_on_submitted_delivery_note(self):
		"""Verify submitting draft Packing Slips on an already submitted Delivery Note."""
		# 1. Create and submit Delivery Note without packing slips
		dn = self._create_test_delivery_note()
		dn.submit()
		self.assertEqual(dn.docstatus, 1)

		# 2. Generate 3 packing slips on the submitted Delivery Note
		res = generate_packing_slips(
			delivery_note=dn.name,
			packing_type="single",
			item_code=self.item_code,
			qty_per_box=100,
			no_of_boxes=3,
		)
		ps_names = res["created_packing_slips"]
		self.assertEqual(len(ps_names), 3)

		# Verify they are initially created as Draft (docstatus: 0)
		for ps_name in ps_names:
			self.assertEqual(frappe.db.get_value("Packing Slip", ps_name, "docstatus"), 0)

		# Verify get_packing_slips_list returns docstatus and Draft status label
		slips = get_packing_slips_list(dn.name)
		self.assertEqual(len(slips), 3)
		for s in slips:
			self.assertEqual(s["docstatus"], 0)
			self.assertEqual(s["status"], "Draft")

		# 3. Submit 1 packing slip individually via submit_packing_slips API
		single_sub = submit_packing_slips(dn.name, packing_slip_names=[ps_names[0]])
		self.assertEqual(single_sub["submitted_count"], 1)
		self.assertEqual(frappe.db.get_value("Packing Slip", ps_names[0], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Packing Slip", ps_names[1], "docstatus"), 0)
		self.assertEqual(frappe.db.get_value("Packing Slip", ps_names[2], "docstatus"), 0)

		# 4. Submit remaining draft packing slips in bulk via submit_packing_slips API
		bulk_sub = submit_packing_slips(dn.name)
		self.assertEqual(bulk_sub["submitted_count"], 2)
		self.assertEqual(frappe.db.get_value("Packing Slip", ps_names[1], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Packing Slip", ps_names[2], "docstatus"), 1)

		# 5. Verify get_packing_slips_list now returns Submitted status label for all
		updated_slips = get_packing_slips_list(dn.name)
		for s in updated_slips:
			self.assertEqual(s["docstatus"], 1)
			self.assertEqual(s["status"], "Submitted")

	def test_19_single_warehouse_confinement_validation(self):
		"""Verify Delivery Note items must be confined to a single warehouse only."""
		company = "Sravi Enterprises - Kolapakkam"

		# 1. Delivery Note with single warehouse succeeds
		dn = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"company": company,
				"customer": self.customer_name,
				"posting_date": nowdate(),
				"posting_time": nowtime(),
				"items": [
					{
						"item_code": self.item_code,
						"qty": 50,
						"warehouse": "Stores - SE-K",
					},
					{
						"item_code": self.item_code_2,
						"qty": 30,
						"warehouse": "Stores - SE-K",
					},
				],
			}
		)
		dn.flags.ignore_mandatory = True
		dn.insert(ignore_permissions=True)
		self.assertTrue(dn.name)

		# 2. Delivery Note with multiple distinct warehouses throws ValidationError
		dn_multi_wh = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"company": company,
				"customer": self.customer_name,
				"posting_date": nowdate(),
				"posting_time": nowtime(),
				"items": [
					{
						"item_code": self.item_code,
						"qty": 50,
						"warehouse": "Stores - SE-K",
					},
					{
						"item_code": self.item_code_2,
						"qty": 30,
						"warehouse": "Coimbatore Goodown - SE-K",
					},
				],
			}
		)
		dn_multi_wh.flags.ignore_mandatory = True
		with self.assertRaises(frappe.ValidationError) as ctx:
			dn_multi_wh.insert(ignore_permissions=True)
		self.assertIn("confined to a single warehouse only", str(ctx.exception))

	def test_20_auto_populate_shipping_contact_details(self):
		"""Verify shipping and billing contact details are automatically populated on Delivery Note."""
		company = "Sravi Enterprises - Kolapakkam"

		# 1. Create a customer with a primary contact
		cust_name = "_Test Contact AutoPop Cust"
		cg = frappe.get_all("Customer Group", filters={"is_group": 0}, limit=1)[0].name
		territory = frappe.get_all("Territory", filters={"is_group": 0}, limit=1)[0].name
		if not frappe.db.exists("Customer", cust_name):
			cust = frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": cust_name,
					"customer_group": cg,
					"territory": territory,
					"default_price_list": "Standard Selling",
				}
			).insert(ignore_permissions=True)
		else:
			cust = frappe.get_doc("Customer", cust_name)

		# Create contact
		contact_name = "_Test AutoPop Contact"
		if not frappe.db.exists("Contact", contact_name):
			contact = frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": "_Test AutoPop",
					"last_name": "Contact",
					"phone_nos": [{"phone": "9876543210", "is_primary_mobile_no": 1}],
					"email_ids": [{"email_id": "test.autopop@example.com", "is_primary": 1}],
					"is_primary_contact": 1,
					"links": [{"link_doctype": "Customer", "link_name": cust.name}],
				}
			).insert(ignore_permissions=True)
		else:
			contact = frappe.get_doc("Contact", contact_name)

		cust.customer_primary_contact = contact.name
		cust.save(ignore_permissions=True)

		# 2. Create Delivery Note without explicitly passing shipping_contact_person
		dn = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"company": company,
				"customer": cust.name,
				"posting_date": nowdate(),
				"posting_time": nowtime(),
				"items": [
					{
						"item_code": self.item_code,
						"qty": 10,
						"warehouse": "Stores - SE-K",
					}
				],
			}
		)
		dn.flags.ignore_mandatory = True
		dn.insert(ignore_permissions=True)

		# 3. Assert shipping and billing contact fields are auto-populated
		self.assertEqual(dn.contact_person, contact.name)
		self.assertEqual(dn.shipping_contact_person, contact.name)
		self.assertEqual(dn.shipping_contact_mobile, "9876543210")
		self.assertEqual(dn.shipping_contact_email, "test.autopop@example.com")

	def test_21_partial_deletion_of_packing_slips(self):
		"""Verify non-interrupting partial deletion skipping submitted packing slips."""
		dn = self._create_test_delivery_note()

		gen_res = generate_packing_slips(
			delivery_note=dn.name,
			packing_type="single",
			item_code=self.item_code,
			qty_per_box=100,
			no_of_boxes=3,
		)
		ps_names = gen_res["created_packing_slips"]

		# Submit the first packing slip
		submit_packing_slips(dn.name, packing_slip_names=json.dumps([ps_names[0]]))

		# Attempt to delete all of them
		del_res = delete_packing_slips(dn.name)

		# Should delete 2 and fail 1 (the submitted one)
		self.assertEqual(del_res["deleted_count"], 2)
		self.assertTrue(del_res["partial"])
		self.assertEqual(del_res["remaining_count"], 1)

		# Verify only the submitted one remains
		remaining = frappe.get_all("Packing Slip", filters={"delivery_note": dn.name})
		self.assertEqual(len(remaining), 1)
		self.assertEqual(remaining[0].name, ps_names[0])

	def test_22_cancel_packing_slips(self):
		"""Verify cancellation of submitted packing slips."""
		from core_customizations.core_customizations.delivery_note import cancel_packing_slips

		dn = self._create_test_delivery_note()

		gen_res = generate_packing_slips(
			delivery_note=dn.name,
			packing_type="single",
			item_code=self.item_code,
			qty_per_box=100,
			no_of_boxes=2,
		)
		ps_names = gen_res["created_packing_slips"]

		# Submit both
		submit_packing_slips(dn.name, packing_slip_names=json.dumps(ps_names))

		# Cancel them
		cancel_res = cancel_packing_slips(dn.name, packing_slip_names=json.dumps(ps_names))
		self.assertEqual(cancel_res["cancelled_count"], 2)

		# Verify they are now cancelled (docstatus 2)
		for ps_name in ps_names:
			self.assertEqual(frappe.db.get_value("Packing Slip", ps_name, "docstatus"), 2)
