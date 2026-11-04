# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Tests for deal_customer [BR-CRM-011] - the Customer made when a voice-agent
(CRM Deal) Quotation is submitted, so "Make Sales Order" works - and for a
returning Customer's spoken delivery address being saved to them
[BR-CRM-008].

Each runs the real path: save_request / upsert_quote as the agent would,
Quotation submit, ERPNext's own make_sales_order, Sales Order submit. The
caller categories are pinned to the seed values; every test runs in a
savepoint rolled back afterwards and nothing may commit.
"""

from unittest.mock import patch

import frappe
from erpnext.selling.doctype.quotation.mapper import make_sales_order
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate
from frappe.utils.password import set_encrypted_password

from core_customizations.core_customizations import voice_agent as va
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

KEY = "test-deal-customer-key"
AUTOMATION_USER = "test-deal-customer-automation@example.com"
PACK = "SASB-50INR-PACK-10"
NEW_CALLER = "+917000001301"
CLASH_CALLER = "+917000001302"
OTHER_CLASH = "+917000001303"
LATER_CUSTOMER = "+917000001304"
RETURNING = "+917000001305"
NO_CATEGORY = "+917000001306"
CHENNAI = {"address": "12 Gandhi Street", "city": "Chennai", "pincode": "600128"}
HYDERABAD = {"address": "4 Godown Road", "city": "Hyderabad", "pincode": "500072"}


class TestDealCustomer(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.get_meta("Customer").has_field("crm_deal"):
			raise cls.skipTest(cls, "needs the ERPNext CRM integration (Customer.crm_deal)")
		cls._commit_guard = patch.object(frappe.db, "commit", side_effect=AssertionError("must never commit"))
		cls._commit_guard.start()
		for number in (NEW_CALLER, CLASH_CALLER, OTHER_CLASH, LATER_CUSTOMER, RETURNING, NO_CATEGORY):
			assert not frappe.db.sql(
				"select name from `tabCRM Lead` where right(regexp_replace(ifnull(mobile_no,''),'[^0-9]',''),10)=%s "
				"union select parent from `tabContact Phone` where right(regexp_replace(ifnull(phone,''),'[^0-9]',''),10)=%s",
				(number[-10:], number[-10:]),
			), f"{number} already used on this site"
		if not frappe.db.exists("User", AUTOMATION_USER):
			user = frappe.get_doc({"doctype": "User", "email": AUTOMATION_USER, "first_name": "Deal Customer Test", "send_welcome_email": 0})
			user.insert(ignore_permissions=True)
			user.add_roles("Sales User")
		set_encrypted_password(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE, KEY, "webhook_secret")

		from core_customizations.patches.v1_0.seed_sarvam_voice_agent_rules import CALLER_CATEGORIES, PACK_ITEMS

		settings = frappe.get_single(SARVAM_SETTINGS_DOCTYPE)
		settings.caller_gate_automation_user = AUTOMATION_USER
		settings.caller_categories = []
		for category, group, price_list, is_default in CALLER_CATEGORIES:
			settings.append("caller_categories", {"category": category, "customer_group": group, "price_list": price_list, "is_default": is_default})
		settings.pack_items = []
		for item_code, group, rule in PACK_ITEMS:
			settings.append("pack_items", {"item_code": item_code, "customer_group": group, "shipping_rule": rule})
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)
		cls.returning = cls._customer("VA DC Returning Customer", RETURNING)

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		cls._commit_guard.stop()
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)
		super().tearDownClass()

	@classmethod
	def _customer(cls, name, mobile, address=True):
		customer = frappe.get_doc(
			{
				"doctype": "Customer", "customer_name": name, "customer_group": "Individual", "customer_type": "Individual",
				"default_price_list": "Standard Selling", "gst_category": "Unregistered",
			}
		).insert(ignore_permissions=True)
		if address:
			frappe.get_doc(
				{
					"doctype": "Address", "address_title": name, "address_type": "Billing", "address_line1": "1 Test Street",
					"city": "Chennai", "state": "Tamil Nadu", "pincode": "600128", "country": "India", "gst_category": "Unregistered",
					"is_primary_address": 1, "is_shipping_address": 1, "links": [{"link_doctype": "Customer", "link_name": customer.name}],
				}
			).insert(ignore_permissions=True)
		if mobile:
			frappe.get_doc(
				{
					"doctype": "Contact", "first_name": name, "phone_nos": [{"phone": mobile, "is_primary_mobile_no": 1}],
					"links": [{"link_doctype": "Customer", "link_name": customer.name}],
				}
			).insert(ignore_permissions=True)
		return customer.name

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("deal_customer_test")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="deal_customer_test")

	# --- helpers --------------------------------------------------------------

	def _quote_new_caller(self, phone, name, address=CHENNAI, category="individual"):
		result = va.save_request(phone=phone, key=KEY, name=name, caller_type=category, items=[{"item_code": PACK, "qty": 1}], **address)
		self.assertTrue(result["quotation"], result)
		return result

	def _order(self, quotation):
		so = make_sales_order(quotation)
		so.delivery_date = add_days(nowdate(), 2)
		if so.meta.has_field("custom_sales_person"):
			so.custom_sales_person = "Administrator"
		so.insert()
		so.submit()
		return so

	def _addresses(self, doctype, name):
		return frappe.get_all("Dynamic Link", {"parenttype": "Address", "link_doctype": doctype, "link_name": name}, pluck="parent")

	# --- the Customer at submit ----------------------------------------------

	def test_new_caller_quote_becomes_a_sales_order(self):
		saved = self._quote_new_caller(NEW_CALLER, "VA DC New Caller")
		quotation = frappe.get_doc("Quotation", saved["quotation"])
		quotation.submit()

		customer = frappe.get_doc("Customer", {"crm_deal": saved["deal"]})
		self.assertEqual(
			(customer.customer_name, customer.customer_group, customer.default_price_list, customer.customer_type),
			("VA DC New Caller", "Individual", quotation.selling_price_list, "Individual"),
		)
		self.assertEqual(frappe.db.get_value("CRM Deal", saved["deal"], "erpnext_customer"), customer.name)
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "crm_deal"), saved["deal"])
		self.assertIn(saved["address"], self._addresses("Customer", customer.name), "the Lead's address follows")
		contact_phone = frappe.db.get_value("Contact Phone", {"parent": customer.customer_primary_contact}, "phone")
		self.assertEqual(contact_phone[-10:], NEW_CALLER[-10:])

		so = self._order(quotation.name)
		self.assertEqual((so.customer, so.shipping_address_name, so.status), (customer.name, saved["address"], "To Deliver and Bill"))
		self.assertEqual(so.rounded_total, quotation.rounded_total)

	def test_a_name_another_customer_has_gets_the_callers_digits(self):
		other = self._customer("VA DC Ravi Kumar", OTHER_CLASH)
		saved = self._quote_new_caller(CLASH_CALLER, "VA DC Ravi Kumar")
		frappe.get_doc("Quotation", saved["quotation"]).submit()
		customer = frappe.db.get_value("Customer", {"crm_deal": saved["deal"]}, ["name", "customer_name"], as_dict=True)
		self.assertNotEqual(customer.name, other)
		self.assertEqual(customer.customer_name, f"VA DC Ravi Kumar - {CLASH_CALLER[-4:]}")
		self.assertEqual(self._order(saved["quotation"]).customer, customer.name, "never the other Ravi Kumar")

	def test_caller_who_became_a_customer_is_reused(self):
		saved = self._quote_new_caller(LATER_CUSTOMER, "VA DC Later Customer")
		existing = self._customer("VA DC Later Customer Ltd", LATER_CUSTOMER, address=False)
		before = frappe.db.count("Customer")
		frappe.get_doc("Quotation", saved["quotation"]).submit()
		self.assertEqual(frappe.db.count("Customer"), before, "no second Customer")
		self.assertEqual(frappe.db.get_value("Customer", existing, "crm_deal"), saved["deal"])
		self.assertIn(saved["address"], self._addresses("Customer", existing))
		self.assertEqual(self._order(saved["quotation"]).customer, existing)

	def test_customer_entered_on_the_deal_is_used(self):
		saved = self._quote_new_caller(NEW_CALLER, "VA DC Staff Picked")
		frappe.db.set_value("CRM Deal", saved["deal"], "erpnext_customer", self.returning)
		before = frappe.db.count("Customer")
		frappe.get_doc("Quotation", saved["quotation"]).submit()
		self.assertEqual(frappe.db.count("Customer"), before)
		so = self._order(saved["quotation"])
		self.assertEqual((so.customer, so.shipping_address_name), (self.returning, saved["address"]))

	def test_no_caller_category_refuses_the_submit_with_what_to_do(self):
		saved = self._quote_new_caller(NO_CATEGORY, "VA DC No Category")
		lead = frappe.db.get_value("CRM Deal", saved["deal"], "lead")
		frappe.db.set_value("CRM Lead", lead, "custom_caller_category", None)
		before = frappe.db.count("Customer")
		with self.assertRaisesRegex(frappe.ValidationError, "Customer in ERPNext"):
			frappe.get_doc("Quotation", saved["quotation"]).submit()
		self.assertEqual(frappe.db.get_value("Quotation", saved["quotation"], "docstatus"), 0)
		self.assertEqual(frappe.db.count("Customer"), before)

	def test_customer_quotation_is_untouched(self):
		quote = va.upsert_quote(phone=RETURNING, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		before = frappe.db.count("Customer")
		frappe.get_doc("Quotation", quote["quotation"]).submit()
		self.assertEqual(frappe.db.count("Customer"), before)
		self.assertEqual(self._order(quote["quotation"]).customer, self.returning)

	# --- a returning Customer's spoken address [BR-CRM-008] --------------------

	def test_returning_customers_new_address_is_saved_and_used(self):
		quote = va.upsert_quote(phone=RETURNING, key=KEY, items=[{"item_code": PACK, "qty": 1}], **HYDERABAD)
		self.assertEqual((quote["status"], quote["warnings"]), ("quoted", []), quote)
		address = frappe.get_doc("Address", quote["address"])
		self.assertEqual((address.city, address.pincode, address.state, address.address_type), ("Hyderabad", "500072", "Telangana", "Shipping"))
		self.assertIn(quote["address"], self._addresses("Customer", self.returning))
		self.assertEqual(address.is_shipping_address, 0, "the Customer's preferred address is left alone")
		self.assertEqual(frappe.db.get_value("Quotation", quote["quotation"], "shipping_address_name"), quote["address"])

		again = va.upsert_quote(phone=RETURNING, key=KEY, items=[{"item_code": PACK, "qty": 2}], **HYDERABAD)
		self.assertEqual(again["address"], quote["address"], "the same line and pincode is reused")
		frappe.get_doc("Quotation", again["quotation"]).submit()
		self.assertEqual(self._order(again["quotation"]).shipping_address_name, quote["address"])

	def test_save_request_saves_a_customers_new_address(self):
		saved = va.save_request(phone=RETURNING, key=KEY, items=[{"item_code": PACK, "qty": 1}], **HYDERABAD)
		self.assertIn(saved["address"], self._addresses("Customer", self.returning))
		self.assertEqual(frappe.db.get_value("Quotation", saved["quotation"], "shipping_address_name"), saved["address"])

	def test_failed_quote_saves_no_address(self):
		before = len(self._addresses("Customer", self.returning))
		result = va.upsert_quote(phone=RETURNING, key=KEY, items=[{"item_code": "VA-DC-NO-SUCH-ITEM", "qty": 1}], **HYDERABAD)
		self.assertEqual(result["error"], "ITEM_NOT_AVAILABLE")
		self.assertEqual(len(self._addresses("Customer", self.returning)), before)

	def test_address_without_a_city_still_quotes_on_the_pincode(self):
		quote = va.upsert_quote(phone=RETURNING, key=KEY, items=[{"item_code": PACK, "qty": 1}], address="4 Godown Road", pincode="500072")
		self.assertEqual((quote["status"], quote["address"]), ("quoted", None))
		self.assertEqual(quote["warnings"], ["ADDRESS_NOT_SAVED: missing city"])

	# --- the Deal shows its Customer [BR-CRM-004] -------------------------------

	def test_a_customers_deal_shows_its_customer(self):
		quote = va.upsert_quote(phone=RETURNING, key=KEY, items=[{"item_code": PACK, "qty": 1}], ship_to_pincode="600128")
		self.assertEqual(frappe.db.get_value("CRM Deal", quote["deal"], "erpnext_customer"), self.returning)
		saved = va.save_request(phone=RETURNING, key=KEY, notes="Call me about an order")
		self.assertEqual(saved["deal"], quote["deal"], "the same Deal is reused")
		self.assertEqual(frappe.db.get_value("CRM Deal", saved["deal"], "erpnext_customer"), self.returning)

	def test_a_customer_entered_on_the_deal_is_never_overwritten(self):
		quote = va.upsert_quote(phone=RETURNING, key=KEY, items=[{"item_code": PACK, "qty": 1}], ship_to_pincode="600128")
		other = self._customer("VA DC Other Customer", None, address=False)
		frappe.db.set_value("CRM Deal", quote["deal"], "erpnext_customer", other)
		va.upsert_quote(phone=RETURNING, key=KEY, items=[{"item_code": PACK, "qty": 2}], ship_to_pincode="600128")
		self.assertEqual(frappe.db.get_value("CRM Deal", quote["deal"], "erpnext_customer"), other)

	def test_a_request_with_no_items_links_the_deal_too(self):
		saved = va.save_request(phone=RETURNING, key=KEY, notes="Call me about an order")
		self.assertEqual(frappe.db.get_value("CRM Deal", saved["deal"], "erpnext_customer"), self.returning)
