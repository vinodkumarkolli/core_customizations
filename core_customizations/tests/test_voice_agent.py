# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Tests for voice_agent - the Sarvam voice agent's one-call-per-job methods:
caller_context / call_started [BR-TEL-007], preferences [BR-CRM-007],
upsert_quote [BR-CRM-006], save_request [BR-CRM-004], transfer_target
[BR-TEL-006] and apply_call_outcome [BR-TEL-007].

Every case the agent can meet is covered: blocked, foreign, unknown number,
lead-only, customer-only, lead plus customer, duplicate lead, legacy spaced
number, and idempotent repeat calls.

Fixtures are created once per class; each test runs inside a savepoint that
is rolled back afterwards, and the class's own rollback removes the rest.
Nothing here may commit: `frappe.db.commit` is patched to fail for the whole
class (a commit would persist the fixtures and the test automation-user /
webhook-secret settings), and `create_request_log` - which commits - is
stubbed in the one test that reaches it.
"""

import json
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt
from frappe.utils.password import set_encrypted_password

from core_customizations.core_customizations import voice_agent as va
from core_customizations.core_customizations.caller_gate import without_webhook_key
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

KEY = "test-voice-agent-key"
AUTOMATION_USER = "test-voice-agent-automation@example.com"
COMPANY = "Sravi Enterprises - Kolapakkam"
PACK = "SASB-50INR-PACK-10"
LOOSE = "SASB-12.6 ML"  # not a pack - sold to any customer group
STANDARD_PACK_RATE = 476.25  # Standard Selling, the settings default for "individual"

# Test-only numbers (none exist on the site - asserted in setUpClass).
BLOCKED = "+917000001101"
FOREIGN = "+14155552671"
UNKNOWN = "+917000001102"
LEAD_ONLY = "+917000001103"
CUSTOMER_ONLY = "+917000001104"
LEAD_AND_CUSTOMER = "+917000001105"
LEGACY_SPACED_STORED = "70000 01106"  # how the legacy row is stored
LEGACY_SPACED_CALLER = "+917000001106"  # how Sarvam reports the caller
COMMERCIAL_CUSTOMER = "+917000001107"
NEW_CALLER = "+917000001108"
NO_ADDRESS_CUSTOMER = "+917000001110"
THREE_ADDRESS_CUSTOMER = "+917000001111"
CONVERTING_CALLER = "+917000001112"
TWIN_SEED = "+917000001113"
OTHER_LEAD = "+917000001114"

TEST_NUMBERS = [
	BLOCKED, UNKNOWN, LEAD_ONLY, CUSTOMER_ONLY, LEAD_AND_CUSTOMER, LEGACY_SPACED_CALLER, COMMERCIAL_CUSTOMER,
	NEW_CALLER, NO_ADDRESS_CUSTOMER, THREE_ADDRESS_CUSTOMER, CONVERTING_CALLER, TWIN_SEED, OTHER_LEAD,
]
ADDRESS_KEYS = {
	"name", "address_title", "address_type", "address_line1", "address_line2", "city", "state", "pincode",
	"is_primary_address", "is_shipping_address",
}


def _ist(*args):
	return datetime(*args, tzinfo=ZoneInfo("Asia/Kolkata"))


class TestVoiceAgent(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._commit_guard = patch.object(
			frappe.db, "commit", side_effect=AssertionError("test_voice_agent must never commit")
		)
		cls._commit_guard.start()
		# These numbers must be free on the site - a real record on one of them
		# (e.g. a persistent "VA Test" fixture) would be resolved instead of the
		# test's own, so check every place a caller's number is matched.
		for number in TEST_NUMBERS:
			last10 = number[-10:]
			for doctype, column in (("CRM Lead", "mobile_no"), ("CRM Lead", "phone"), ("Contact", "mobile_no"), ("Contact Phone", "phone"), ("Customer", "mobile_no")):
				assert not frappe.db.sql(
					f"select name from `tab{doctype}` where right(regexp_replace(ifnull({column},''),'[^0-9]',''),10)=%s",
					last10,
				), f"{number} already used on this site ({doctype}.{column})"

		if not frappe.db.exists("User", AUTOMATION_USER):
			user = frappe.get_doc(
				{"doctype": "User", "email": AUTOMATION_USER, "first_name": "Voice Agent Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")

		# Written inside the test transaction - the class rollback restores the
		# site's own secret, so it is never read, copied or rewritten here.
		set_encrypted_password(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE, KEY, "webhook_secret")
		frappe.db.set_single_value(SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user", AUTOMATION_USER)
		cls._pin_settings()
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)

		frappe.get_doc({"doctype": "Blocked Contact", "mobile_no": BLOCKED[-10:], "enabled": 1, "reason": "test"}).insert(
			ignore_permissions=True
		)

		cls.lead_only = cls._lead("VA Lead Only", LEAD_ONLY, category="individual", address="Address: 12 Kukatpally, Hyderabad 500072")
		cls.lead_with_customer = cls._lead("VA Lead And Customer", LEAD_AND_CUSTOMER, organization="VA Unit Individual Customer")
		legacy = cls._lead("VA Legacy Spaced", LEGACY_SPACED_CALLER)
		# Bypass before_validate normalisation - this is what a pre-hook row looks like.
		frappe.db.set_value("CRM Lead", legacy, "mobile_no", LEGACY_SPACED_STORED)
		cls.legacy_lead = legacy

		cls.customer_only = cls._customer("VA Unit Individual Customer", "Individual", CUSTOMER_ONLY)
		cls.commercial = cls._customer("VA Unit Commercial Customer", "Commercial", COMMERCIAL_CUSTOMER)
		cls.no_address = cls._customer("VA Unit No Address Customer", "Individual", NO_ADDRESS_CUSTOMER, address=False)

		# Three enabled addresses + one disabled, created so the expected order is
		# shipping (Hyderabad) -> primary (Chennai billing) -> newest (Coimbatore).
		cls.three = cls._customer("VA Unit Three Address Customer", "Individual", THREE_ADDRESS_CUSTOMER)
		cls.three_primary = frappe.db.get_value(
			"Dynamic Link", {"parenttype": "Address", "link_doctype": "Customer", "link_name": cls.three}, "parent"
		)
		cls.three_disabled = cls._address(cls.three, "Disabled Rd", "Madurai", "Tamil Nadu", "625001", shipping=1, disabled=1)
		cls.three_shipping = cls._address(cls.three, "Godown Rd", "Hyderabad", "Telangana", "500062", shipping=1)
		cls.three_newest = cls._address(cls.three, "Branch Rd", "Coimbatore", "Tamil Nadu", "641001", address_type="Billing")

		# Price lists for the price-list resolution tests - each pack-10 rate is
		# different, so a quote taken from the wrong list fails on the rate.
		cls._price_list("VA Unit Customer List", {PACK: 470, LOOSE: 40})
		cls._price_list("VA Unit Group List", {PACK: 460, LOOSE: 39})
		cls._price_list("VA Unit No Pack List", {LOOSE: 38})
		cls._price_list("VA Unit Disabled List", {PACK: 450}, enabled=0)
		cls._price_list("VA Unit Buying List", {PACK: 440}, selling=0)
		cls._price_list("VA Unit USD List", {PACK: 6}, currency="USD")

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		cls._commit_guard.stop()
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)
		super().tearDownClass()

	@classmethod
	def _lead(cls, name, mobile, category=None, organization=None, address=None):
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Lead",
					"first_name": name,
					"mobile_no": mobile,
					"status": "New",
					"lead_owner": "Administrator",
					"organization": organization,
					"custom_caller_category": category,
					"company_description": address,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	@classmethod
	def _pin_settings(cls):
		"""
		Caller Categories and Pack Items as the seed patch sets them, whatever
		the site's own settings currently hold (staff edit them) - written in
		this class's transaction, so the class rollback restores the site's.
		"""
		from core_customizations.patches.v1_0.seed_sarvam_voice_agent_rules import CALLER_CATEGORIES, PACK_ITEMS

		settings = frappe.get_single(SARVAM_SETTINGS_DOCTYPE)
		settings.caller_categories = []
		for category, group, price_list, is_default in CALLER_CATEGORIES:
			settings.append("caller_categories", {"category": category, "customer_group": group, "price_list": price_list, "is_default": is_default})
		settings.pack_items = []
		for item_code, group, rule in PACK_ITEMS:
			settings.append("pack_items", {"item_code": item_code, "customer_group": group, "shipping_rule": rule})
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)

	@classmethod
	def _price_list(cls, name, rates, enabled=1, selling=1, currency="INR"):
		frappe.get_doc(
			{"doctype": "Price List", "price_list_name": name, "enabled": 1, "selling": selling, "buying": int(not selling), "currency": currency}
		).insert(ignore_permissions=True)
		for item_code, rate in rates.items():
			frappe.get_doc({"doctype": "Item Price", "item_code": item_code, "price_list": name, "price_list_rate": rate}).insert(ignore_permissions=True)
		if not enabled:
			# ERPNext refuses Item Prices on a disabled list - disable it afterwards,
			# as happens when a list with prices is retired.
			frappe.db.set_value("Price List", name, "enabled", 0)

	@classmethod
	def _address(cls, customer, line, city, state, pincode, address_type="Shipping", shipping=0, disabled=0):
		return (
			frappe.get_doc(
				{
					"doctype": "Address",
					"address_title": f"{customer} {city}",
					"address_type": address_type,
					"address_line1": line,
					"city": city,
					"state": state,
					"pincode": pincode,
					"country": "India",
					"gst_category": "Unregistered",
					"is_shipping_address": shipping,
					"disabled": disabled,
					"links": [{"link_doctype": "Customer", "link_name": customer}],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	@classmethod
	def _customer(cls, name, group, mobile, address=True):
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_group": group,
				"customer_type": "Individual",
				"default_price_list": "Standard Selling",
				"gst_category": "Unregistered",
			}
		).insert(ignore_permissions=True)
		if address:
			frappe.get_doc(
				{
					"doctype": "Address",
					"address_title": name,
					"address_type": "Billing",
					"address_line1": "1 Test Street",
					"city": "Chennai",
					"state": "Tamil Nadu",
					"pincode": "600128",
					"country": "India",
					"gst_category": "Unregistered",
					"is_primary_address": 1,
					"links": [{"link_doctype": "Customer", "link_name": customer.name}],
				}
			).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": name,
				"phone_nos": [{"phone": mobile, "is_primary_mobile_no": 1}],
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		).insert(ignore_permissions=True)
		return customer.name

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("voice_agent_test")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="voice_agent_test")
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)

	# --- auth ---------------------------------------------------------------

	def test_wrong_key_is_refused_by_every_method(self):
		for method in (va.caller_context, va.upsert_quote, va.save_request, va.transfer_target, va.get_caller_preferences):
			with self.subTest(method=method.__name__), self.assertRaises(frappe.PermissionError):
				method(phone=UNKNOWN, key="wrong")

	# --- blocked / foreign: no data, no writes ----------------------------

	def test_blocked_and_foreign_callers_get_nothing_from_any_method(self):
		for phone, reason in ((BLOCKED, "BLOCKED_LIST"), (FOREIGN, "FOREIGN_NUMBER")):
			calls = {
				"caller_context": lambda: va.caller_context(phone=phone, key=KEY, call_id=f"va-blocked-{phone}"),
				"get_caller_preferences": lambda: va.get_caller_preferences(phone=phone, key=KEY),
				"set_caller_preferences": lambda: va.set_caller_preferences(phone=phone, key=KEY, preferences={"a": 1}),
				"upsert_quote": lambda: va.upsert_quote(phone=phone, key=KEY, items=[{"item_code": PACK, "qty": 1}]),
				"save_request": lambda: va.save_request(phone=phone, key=KEY, name="Blocked Person"),
				"transfer_target": lambda: va.transfer_target(phone=phone, key=KEY),
			}
			for name, call in calls.items():
				with self.subTest(phone=phone, method=name):
					result = call()
					self.assertFalse(result["allowed"])
					self.assertEqual(result["reason"], reason)
					self.assertNotIn("lead", {k for k, v in result.items() if v})
			self.assertFalse(frappe.db.exists("CRM Call Log", f"va-blocked-{phone}"))
		self.assertFalse(frappe.db.exists("CRM Lead", {"first_name": "Blocked Person"}))

	# --- caller_context -----------------------------------------------------

	def test_unknown_number(self):
		result = va.caller_context(phone=UNKNOWN, key=KEY)
		self.assertTrue(result["allowed"])
		self.assertIsNone(result["lead"])
		self.assertIsNone(result["contact"])
		self.assertIsNone(result["customer"])
		self.assertEqual(result["preferences"], {})
		self.assertIsNone(result["call_log"])

	def test_lead_only(self):
		result = va.caller_context(phone=LEAD_ONLY, key=KEY)
		self.assertEqual(result["lead"]["name"], self.lead_only)
		self.assertEqual(result["lead"]["caller_category"], "individual")
		self.assertIsNone(result["customer"])

	def test_customer_only_via_contact_dynamic_link(self):
		result = va.caller_context(phone=CUSTOMER_ONLY, key=KEY)
		self.assertIsNone(result["lead"])
		self.assertIsNotNone(result["contact"])
		self.assertEqual(result["customer"]["name"], self.customer_only)
		self.assertEqual(result["customer"]["customer_group"], "Individual")
		self.assertEqual(result["customer"]["category"], "individual")
		self.assertTrue(result["customer"]["group_supported"])

	def test_lead_plus_customer_via_organization(self):
		result = va.caller_context(phone=LEAD_AND_CUSTOMER, key=KEY)
		self.assertEqual(result["lead"]["name"], self.lead_with_customer)
		self.assertEqual(result["customer"]["name"], self.customer_only)

	def test_mahaveer_agencies_ramapuram_resolves_as_customer(self):
		if not frappe.db.exists("Customer", "Mahaveer Agencies - Ramapuram"):
			self.skipTest("site data not present")
		result = va.caller_context(phone="+919840456658", key=KEY)
		if not result["allowed"]:
			self.skipTest("number is on this site's blocked list")
		self.assertEqual(result["customer"]["name"], "Mahaveer Agencies - Ramapuram")
		self.assertEqual(result["customer"]["customer_group"], "Commercial")
		self.assertEqual(result["customer"]["default_price_list"], "Distributor Pricelist 40.50")

	def test_legacy_spaced_number_matches_every_caller_spelling(self):
		for spelling in (LEGACY_SPACED_CALLER, "917000001106", "07000001106", "7000001106", "+91 70000-01106"):
			with self.subTest(spelling=spelling):
				self.assertEqual(va.caller_context(phone=spelling, key=KEY)["lead"]["name"], self.legacy_lead)

	def test_call_log_is_created_once_per_call_id(self):
		first = va.caller_context(phone=LEAD_ONLY, key=KEY, call_id="va-test-call-1")
		second = va.caller_context(phone=LEAD_ONLY, key=KEY, call_id="va-test-call-1")
		self.assertEqual(first["call_log"], {"id": "va-test-call-1", "created": True})
		self.assertEqual(second["call_log"], {"id": "va-test-call-1", "created": False})
		self.assertEqual(frappe.db.count("CRM Call Log", {"id": "va-test-call-1"}), 1)
		log = frappe.get_doc("CRM Call Log", "va-test-call-1")
		self.assertEqual((log.type, log.status, log.reference_docname), ("Incoming", "In Progress", self.lead_only))

	def test_call_started_webhook_reads_sarvam_payload_keys(self):
		with patch.object(frappe, "request", None, create=True), patch.object(va, "create_request_log") as request_log:
			result = va.call_started(key=KEY, user_phone_number=LEAD_ONLY, interaction_id="va-test-call-2", agent_phone_number="+918064276261")
		self.assertEqual(result["lead"]["name"], self.lead_only)
		self.assertEqual(result["call_log"]["id"], "va-test-call-2")
		self.assertEqual(frappe.db.get_value("CRM Call Log", "va-test-call-2", "to"), "+918064276261")
		self.assertEqual(request_log.call_args.kwargs["request_description"], "Sarvam Call Started")
		self.assertNotIn("key", request_log.call_args.args[0], "the webhook secret must not be logged")

	# --- preferences --------------------------------------------------------

	def test_preferences_merge_and_are_returned_in_caller_context(self):
		va.set_caller_preferences(phone=LEAD_ONLY, key=KEY, preferences=json.dumps({"preferred_language": "ta"}))
		result = va.set_caller_preferences(phone=LEAD_ONLY, key=KEY, preferences={"preferred_flow": "order"})
		self.assertEqual(result["preferences"], {"preferred_language": "ta", "preferred_flow": "order"})
		self.assertEqual(result["source"], f"CRM Lead:{self.lead_only}")
		self.assertEqual(va.caller_context(phone=LEAD_ONLY, key=KEY)["preferences"]["preferred_language"], "ta")

		replaced = va.set_caller_preferences(phone=LEAD_ONLY, key=KEY, preferences={"preferred_flow": "enquiry"}, merge=0)
		self.assertEqual(replaced["preferences"], {"preferred_flow": "enquiry"})

	def test_preferences_for_customer_only_caller_live_on_contact(self):
		result = va.set_caller_preferences(phone=CUSTOMER_ONLY, key=KEY, preferences={"preferred_language": "te"})
		self.assertTrue(result["source"].startswith("Contact:"))
		self.assertEqual(va.get_caller_preferences(phone=CUSTOMER_ONLY, key=KEY)["preferences"], {"preferred_language": "te"})

	def test_preferences_for_unknown_caller_are_not_saved(self):
		result = va.set_caller_preferences(phone=UNKNOWN, key=KEY, preferences={"preferred_language": "ta"})
		self.assertFalse(result["saved"])
		self.assertEqual(result["error"], "NOT_ON_RECORD")

	# --- upsert_quote -------------------------------------------------------

	def _assert_matches_saved_quotation(self, result):
		doc = frappe.get_doc("Quotation", result["quotation"])
		self.assertEqual(result["net_total"], doc.net_total)
		self.assertEqual(result["grand_total"], doc.grand_total)
		self.assertEqual(result["rounded_total"], doc.rounded_total)
		self.assertAlmostEqual(result["net_total"] + sum(t["amount"] for t in result["taxes"]) + result["shipping"], doc.grand_total, 2)
		return doc

	def test_pack_quote_for_individual_lead_out_of_state(self):
		result = va.upsert_quote(phone=LEAD_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		self.assertEqual(result["status"], "quoted", result)
		doc = self._assert_matches_saved_quotation(result)
		self.assertEqual((doc.quotation_to, doc.party_name), ("CRM Deal", result["deal"]))
		self.assertEqual(frappe.db.get_value("CRM Deal", result["deal"], "lead"), self.lead_only)
		self.assertEqual(result["price_list"], "Standard Selling")
		self.assertEqual([t["type"] for t in result["taxes"]], ["IGST"])
		self.assertEqual(result["taxes"][0]["rate"], 5.0)
		self.assertEqual(doc.shipping_rule, "Next Day Shipping")
		self.assertGreater(result["shipping"], 0)
		self.assertEqual(result["total_to_say"], doc.rounded_total)

	def test_pack_quote_in_state_splits_cgst_sgst(self):
		result = va.upsert_quote(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 2}])
		self.assertEqual(result["status"], "quoted", result)
		doc = self._assert_matches_saved_quotation(result)
		self.assertEqual((doc.quotation_to, doc.party_name), ("Customer", self.customer_only))
		self.assertEqual(sorted(t["type"] for t in result["taxes"]), ["CGST", "SGST"])
		self.assertTrue(all(t["rate"] == 2.5 for t in result["taxes"]))

	def test_repeat_quote_updates_the_same_draft(self):
		first = va.upsert_quote(phone=LEAD_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		second = va.upsert_quote(phone=LEAD_ONLY, key=KEY, items=json.dumps([{"item_code": PACK, "qty": 3}]))
		self.assertTrue(first["created"])
		self.assertFalse(second["created"])
		self.assertEqual(first["quotation"], second["quotation"])
		self.assertEqual(first["deal"], second["deal"])
		self.assertEqual(second["items"][0]["qty"], 3)
		self._assert_matches_saved_quotation(second)

	def test_pack_refused_for_commercial_customer(self):
		result = va.upsert_quote(phone=COMMERCIAL_CUSTOMER, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		self.assertEqual(result["error"], "PACK_NOT_AVAILABLE")
		self.assertFalse(frappe.db.exists("Quotation", {"party_name": self.commercial, "docstatus": 0}))

	def test_quote_needs_a_pincode_when_none_is_on_record(self):
		lead = self._lead("VA No Address", NEW_CALLER, category="individual")
		result = va.upsert_quote(phone=NEW_CALLER, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		self.assertEqual(result["error"], "PINCODE_REQUIRED")
		self.assertFalse(frappe.db.exists("CRM Deal", {"lead": lead}), "a failed quote must leave nothing behind")

		with_pin = va.upsert_quote(phone=NEW_CALLER, key=KEY, items=[{"item_code": PACK, "qty": 1}], ship_to_pincode="600128")
		self.assertEqual(with_pin["status"], "quoted", with_pin)
		self.assertEqual(sorted(t["type"] for t in with_pin["taxes"]), ["CGST", "SGST"])

	def test_quote_for_unknown_caller_or_unquotable_category(self):
		self.assertEqual(va.upsert_quote(phone=UNKNOWN, key=KEY, items=[{"item_code": PACK, "qty": 1}])["error"], "NOT_ON_RECORD")
		self._lead("VA Retailer", NEW_CALLER, category="retailer", address="Address: Chennai 600128")
		self.assertEqual(va.upsert_quote(phone=NEW_CALLER, key=KEY, items=[{"item_code": PACK, "qty": 1}])["error"], "QUOTE_NOT_AVAILABLE")

	def test_quote_rejects_bad_items(self):
		self.assertEqual(va.upsert_quote(phone=LEAD_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 0}])["error"], "INVALID_ITEMS")
		self.assertEqual(va.upsert_quote(phone=LEAD_ONLY, key=KEY, items=[])["error"], "INVALID_ITEMS")

	# --- save_request ---------------------------------------------------------

	def test_new_caller_gets_lead_and_callback_task(self):
		result = va.save_request(
			phone=NEW_CALLER, key=KEY, name="VA New Caller", caller_type="Retailer", store_type="Pharmacy",
			area="Ramapuram", address="5 Main Road, Chennai 600089", notes="Wants distributor rates", whatsapp_number="+917000000999",
		)
		self.assertEqual(result["status"], "saved", result)
		lead = frappe.get_doc("CRM Lead", result["lead"])
		self.assertEqual((lead.mobile_no, lead.custom_caller_category, lead.custom_store_type), (NEW_CALLER, "retailer", "Pharmacy"))
		self.assertIn("Address: 5 Main Road, Chennai 600089", lead.company_description)
		task = frappe.get_doc("CRM Task", result["task"])
		self.assertEqual((task.reference_doctype, task.reference_docname, task.status), ("CRM Lead", lead.name, "Todo"))
		self.assertIn("CUSTOMER_GROUP_NEEDS_REVIEW: retailer", result["warnings"])
		self.assertIsNone(result["quotation"])

	def test_new_individual_caller_with_items_gets_deal_and_quotation(self):
		result = va.save_request(
			phone=NEW_CALLER, key=KEY, name="VA Pack Buyer", caller_type="individual",
			items=[{"item_code": PACK, "qty": 1}], address="Plot 45, Kukatpally, Hyderabad 500072",
		)
		self.assertEqual(result["status"], "saved", result)
		self.assertEqual(result["quote"]["status"], "quoted", result["quote"])
		self.assertEqual(frappe.db.get_value("CRM Deal", result["deal"], "lead"), result["lead"])
		self.assertEqual(frappe.db.get_value("Quotation", result["quotation"], "party_name"), result["deal"])
		self.assertTrue(result["task"], "a new lead always gets a callback task")

	def test_existing_lead_is_a_duplicate_not_a_second_lead(self):
		before = frappe.db.count("CRM Lead")
		result = va.save_request(phone=LEAD_ONLY, key=KEY, name="Someone Else", notes="Calling again")
		self.assertEqual(result["status"], "duplicate")
		self.assertEqual(result["lead"], self.lead_only)
		self.assertTrue(result["message"].startswith(f"DUPLICATE_LEAD: name={self.lead_only};"))
		self.assertEqual(frappe.db.count("CRM Lead"), before)
		self.assertEqual(frappe.db.get_value("CRM Task", result["task"], "reference_docname"), self.lead_only)

	def test_legacy_spaced_number_is_a_duplicate(self):
		result = va.save_request(phone=LEGACY_SPACED_CALLER, key=KEY, name="Legacy Again")
		self.assertEqual((result["status"], result["lead"]), ("duplicate", self.legacy_lead))

	def test_repeat_save_request_is_idempotent(self):
		first = va.save_request(phone=NEW_CALLER, key=KEY, name="VA Repeat", caller_type="wholesale")
		second = va.save_request(phone=NEW_CALLER, key=KEY, name="VA Repeat", caller_type="wholesale")
		self.assertEqual(first["status"], "saved")
		self.assertEqual(second["status"], "duplicate")
		self.assertEqual(first["lead"], second["lead"])
		self.assertEqual(first["task"], second["task"])
		self.assertEqual(frappe.db.count("CRM Task", {"reference_docname": first["lead"]}), 1)

	def test_existing_customer_gets_deal_and_draft_quotation(self):
		result = va.save_request(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		self.assertEqual(result["status"], "saved", result)
		self.assertIsNone(result["lead"], "a customer-only caller does not get a CRM Lead")
		self.assertTrue(result["deal"])
		self.assertEqual(frappe.db.get_value("Quotation", result["quotation"], "party_name"), self.customer_only)
		self.assertIsNone(result["task"])

	def test_existing_customer_without_items_gets_deal_and_task(self):
		result = va.save_request(phone=CUSTOMER_ONLY, key=KEY, notes="Call me about an order")
		self.assertTrue(result["deal"])
		self.assertEqual(frappe.db.get_value("CRM Task", result["task"], "reference_doctype"), "CRM Deal")

	def test_new_caller_needs_a_name(self):
		self.assertEqual(va.save_request(phone=NEW_CALLER, key=KEY)["error"], "NAME_REQUIRED")

	def test_lead_creation_race_returns_duplicate(self):
		original = va._resolve

		def stale_resolve(phone):
			# The lookup misses a Lead created a moment ago by a parallel request.
			ctx = original(phone)
			ctx.lead = None
			return ctx

		with patch.object(va, "_resolve", stale_resolve):
			result = va.save_request(phone=LEAD_ONLY, key=KEY, name="Racer")
		self.assertEqual((result["status"], result["lead"]), ("duplicate", self.lead_only))
		self.assertFalse(frappe.db.exists("CRM Lead", {"first_name": "Racer"}))

	def test_blocked_number_added_mid_call_raises_caller_blocked_guard(self):
		with patch.object(va, "evaluate", lambda phone: {"allowed": True, "reason": None, "message": ""}):
			result = va.save_request(phone=BLOCKED, key=KEY, name="Slipped Through")
		self.assertEqual(result["status"], "blocked")
		self.assertTrue(result["message"].startswith("CALLER_BLOCKED:"))
		self.assertFalse(frappe.db.exists("CRM Lead", {"first_name": "Slipped Through"}))

	# --- transfer_target -------------------------------------------------------

	def _transfer(self, phone, when):
		with patch.object(va, "_now", lambda tz: when.astimezone(tz)):
			return va.transfer_target(phone=phone, key=KEY)

	def test_transfer_open_for_known_caller_in_hours(self):
		result = self._transfer(LEAD_ONLY, _ist(2026, 11, 3, 11, 0))  # Tuesday
		self.assertTrue(result["open"])
		executives = [e for e in frappe.get_single(SARVAM_SETTINGS_DOCTYPE).transfer_executives if e.enabled]
		self.assertEqual(result["target"], executives[0].phone)
		self.assertEqual(result["then"], [e.phone for e in executives[1:]])

	def test_transfer_closed_outside_hours_and_on_sunday(self):
		for when in (_ist(2026, 11, 3, 9, 59), _ist(2026, 11, 3, 20, 0), _ist(2026, 11, 8, 12, 0)):
			with self.subTest(when=when):
				result = self._transfer(LEAD_ONLY, when)
				self.assertEqual((result["open"], result["reason"], result["decision"]), (False, "OUTSIDE_HOURS", "CALLBACK"))

	def test_transfer_refused_for_unknown_caller(self):
		result = self._transfer(UNKNOWN, _ist(2026, 11, 3, 11, 0))
		self.assertEqual((result["open"], result["reason"]), (False, "NOT_ON_RECORD"))

	# --- call ended -----------------------------------------------------------

	def test_call_outcome_is_written_once_to_the_started_call_log(self):
		va.caller_context(phone=LEAD_ONLY, key=KEY, call_id="va-test-call-3")
		log = frappe.get_doc("CRM Call Log", "va-test-call-3")
		va.apply_call_outcome(
			log,
			{
				"output_agent_variables": {
					"summary": "Caller ordered one pack of 10.",
					"conversation_ref": "conv-123",
					"preferences": {"preferred_language": "ta"},
				}
			},
		)
		log.reload()
		self.assertEqual(log.custom_conversation_ref, "conv-123")
		self.assertEqual(json.loads(log.custom_agent_variables)["summary"], "Caller ordered one pack of 10.")
		note = frappe.get_doc("FCRM Note", log.note)
		self.assertEqual((note.reference_doctype, note.reference_docname), ("CRM Lead", self.lead_only))
		self.assertEqual(va.get_caller_preferences(phone=LEAD_ONLY, key=KEY)["preferences"], {"preferred_language": "ta"})
		self.assertEqual(frappe.db.count("CRM Call Log", {"id": "va-test-call-3"}), 1)

	# --- saved addresses [BR-CRM-008] ---------------------------------------

	def _quote_taxes(self, result):
		self.assertEqual(result["status"], "quoted", result)
		return sorted((t["type"], t["rate"], t["amount"]) for t in result["taxes"]), result["grand_total"]

	def _with_tax_basis(self, basis):
		frappe.db.set_single_value("Accounts Settings", "determine_address_tax_category_from", basis)
		frappe.clear_document_cache("Accounts Settings", "Accounts Settings")
		self.addCleanup(frappe.clear_document_cache, "Accounts Settings", "Accounts Settings")

	def test_addresses_customer_with_none(self):
		self.assertEqual(va.caller_context(phone=NO_ADDRESS_CUSTOMER, key=KEY)["addresses"], [])

	def test_addresses_customer_with_one(self):
		addresses = va.caller_context(phone=CUSTOMER_ONLY, key=KEY)["addresses"]
		self.assertEqual(len(addresses), 1)
		self.assertEqual(set(addresses[0]), ADDRESS_KEYS, "exact keys - no `disabled`")
		self.assertEqual((addresses[0]["city"], addresses[0]["pincode"]), ("Chennai", "600128"))

	def test_addresses_order_skip_disabled_and_cap(self):
		names = [a["name"] for a in va.caller_context(phone=THREE_ADDRESS_CUSTOMER, key=KEY)["addresses"]]
		self.assertEqual(names, [self.three_shipping, self.three_primary, self.three_newest])
		self.assertNotIn(self.three_disabled, names)

		frappe.db.set_single_value(SARVAM_SETTINGS_DOCTYPE, "address_list_limit", 2)
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)
		capped = [a["name"] for a in va.caller_context(phone=THREE_ADDRESS_CUSTOMER, key=KEY)["addresses"]]
		self.assertEqual(capped, [self.three_shipping, self.three_primary])

	def test_addresses_lead_only_and_blocked(self):
		self.assertEqual(va.caller_context(phone=LEAD_ONLY, key=KEY)["addresses"], [], "never parsed from company_description")
		self.assertEqual(va.caller_context(phone=UNKNOWN, key=KEY)["addresses"], [])
		self.assertNotIn("addresses", va.caller_context(phone=BLOCKED, key=KEY))

	def test_call_started_returns_addresses_too(self):
		with patch.object(frappe, "request", None, create=True), patch.object(va, "create_request_log"):
			result = va.call_started(key=KEY, user_phone_number=CUSTOMER_ONLY, interaction_id="va-test-call-addr")
		self.assertEqual(result["addresses"], va.caller_context(phone=CUSTOMER_ONLY, key=KEY)["addresses"])

	def test_new_caller_address_is_saved_and_linked_to_the_lead(self):
		result = va.save_request(
			phone=NEW_CALLER, key=KEY, name="VA Address Caller", caller_type="individual",
			address="Plot 45, Sai Nagar", city="Hyderabad", pincode="500072",
		)
		self.assertEqual(result["status"], "saved", result)
		address = frappe.get_doc("Address", result["address"])
		self.assertEqual((address.address_type, address.city, address.state, address.pincode), ("Shipping", "Hyderabad", "Telangana", "500072"))
		self.assertEqual([(l.link_doctype, l.link_name) for l in address.links], [("CRM Lead", result["lead"])])
		self.assertIn("Address: Plot 45, Sai Nagar", frappe.db.get_value("CRM Lead", result["lead"], "company_description"))
		self.assertEqual([a["name"] for a in va.caller_context(phone=NEW_CALLER, key=KEY)["addresses"]], [address.name])

		again = va.save_request(phone=NEW_CALLER, key=KEY, name="VA Address Caller", address="Plot 45, Sai Nagar", city="Hyderabad", pincode="500072")
		self.assertEqual(again["address"], address.name, "same address is reused, not duplicated")

	def test_address_without_city_saves_the_request_but_not_an_address(self):
		result = va.save_request(phone=NEW_CALLER, key=KEY, name="VA No City", address="5 Main Road, 600089")
		self.assertEqual(result["status"], "saved")
		self.assertIsNone(result["address"])
		self.assertIn("ADDRESS_NOT_SAVED: missing city", result["warnings"])

	def test_another_customers_address_is_refused_and_nothing_is_saved(self):
		other = self.three_shipping
		quote = va.upsert_quote(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}], address_name=other)
		self.assertEqual((quote["status"], quote["error"]), ("error", "ADDRESS_NOT_ON_RECORD"))
		self.assertTrue(quote["message"])
		self.assertFalse(frappe.db.exists("Quotation", {"party_name": self.customer_only, "docstatus": 0}))

		before = (frappe.db.count("CRM Lead"), frappe.db.count("CRM Task"), frappe.db.count("CRM Deal"))
		for phone, name in ((CUSTOMER_ONLY, None), (NEW_CALLER, "VA Stranger")):
			with self.subTest(phone=phone):
				saved = va.save_request(phone=phone, key=KEY, name=name, items=[{"item_code": PACK, "qty": 1}], address_name=other)
				self.assertEqual((saved["status"], saved["error"]), ("error", "ADDRESS_NOT_ON_RECORD"))
		self.assertEqual((frappe.db.count("CRM Lead"), frappe.db.count("CRM Task"), frappe.db.count("CRM Deal")), before)

	def test_disabled_address_cannot_be_used(self):
		quote = va.upsert_quote(phone=THREE_ADDRESS_CUSTOMER, key=KEY, items=[{"item_code": PACK, "qty": 1}], address_name=self.three_disabled)
		self.assertEqual(quote["error"], "ADDRESS_NOT_ON_RECORD")

	def test_lead_address_gives_same_gst_as_its_pincode(self):
		saved = va.save_request(phone=NEW_CALLER, key=KEY, name="VA Two Addresses", caller_type="individual", address="Plot 45", city="Hyderabad", pincode="500072")
		chennai = va.save_request(phone=NEW_CALLER, key=KEY, address="1 Anna Salai", city="Chennai", pincode="600002")["address"]
		items = [{"item_code": PACK, "qty": 1}]
		for address_name, pincode, expected in ((saved["address"], "500072", ["IGST"]), (chennai, "600002", ["CGST", "SGST"])):
			with self.subTest(pincode=pincode):
				by_address = va.upsert_quote(phone=NEW_CALLER, key=KEY, items=items, address_name=address_name)
				self.assertEqual(frappe.db.get_value("Quotation", by_address["quotation"], "shipping_address_name"), address_name)
				by_pincode = va.upsert_quote(phone=NEW_CALLER, key=KEY, items=items, ship_to_pincode=pincode)
				self.assertEqual(self._quote_taxes(by_address), self._quote_taxes(by_pincode))
				self.assertEqual([t["type"] for t in sorted(by_address["taxes"], key=lambda t: t["type"])], expected)

	def test_address_name_wins_over_pincode(self):
		chennai = va.upsert_quote(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}], ship_to_pincode="500072",
			address_name=va.caller_context(phone=CUSTOMER_ONLY, key=KEY)["addresses"][0]["name"])
		self.assertEqual(sorted(t["type"] for t in chennai["taxes"]), ["CGST", "SGST"])

	def test_customer_address_gst_follows_india_compliance_shipping_basis(self):
		"""With "Determine Address Tax Category From" = Shipping Address, the chosen address decides GST - same as its pincode."""
		self._with_tax_basis("Shipping Address")
		items = [{"item_code": PACK, "qty": 1}]
		lead = self._lead("VA Pincode Reference", NEW_CALLER, category="individual")
		for address_name, pincode, expected in ((self.three_shipping, "500062", ["IGST"]), (self.three_newest, "641001", ["CGST", "SGST"])):
			with self.subTest(pincode=pincode):
				by_address = va.upsert_quote(phone=THREE_ADDRESS_CUSTOMER, key=KEY, items=items, address_name=address_name)
				self.assertEqual(sorted(t["type"] for t in by_address["taxes"]), expected)
				by_pincode = va.upsert_quote(phone=NEW_CALLER, key=KEY, items=items, ship_to_pincode=pincode)
				self.assertEqual(self._quote_taxes(by_address), self._quote_taxes(by_pincode))
		self.assertTrue(lead)

	def test_customer_address_gst_follows_billing_when_site_uses_billing_basis(self):
		"""This site's current setting: GST follows the billing address, whichever shipping address is chosen (as in Desk)."""
		self._with_tax_basis("Billing Address")
		quote = va.upsert_quote(phone=THREE_ADDRESS_CUSTOMER, key=KEY, items=[{"item_code": PACK, "qty": 1}], address_name=self.three_shipping)
		self.assertEqual(frappe.db.get_value("Quotation", quote["quotation"], "shipping_address_name"), self.three_shipping)
		self.assertEqual(sorted(t["type"] for t in quote["taxes"]), ["CGST", "SGST"], "billing address is in Tamil Nadu")

	def test_lead_addresses_follow_the_lead_to_its_customer(self):
		saved = va.save_request(phone=CONVERTING_CALLER, key=KEY, name="VA Converting", caller_type="individual", address="7 Lake View", city="Chennai", pincode="600040")
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "VA Converted Customer", "customer_group": "Individual", "customer_type": "Individual",
			 "default_price_list": "Standard Selling", "gst_category": "Unregistered", "mobile_no": CONVERTING_CALLER}
		).insert(ignore_permissions=True)
		links = frappe.get_all("Dynamic Link", {"parenttype": "Address", "parent": saved["address"]}, ["link_doctype", "link_name"])
		self.assertCountEqual([(l.link_doctype, l.link_name) for l in links], [("CRM Lead", saved["lead"]), ("Customer", customer.name)])
		self.assertEqual([a["name"] for a in va.caller_context(phone=CONVERTING_CALLER, key=KEY)["addresses"]], [saved["address"]])

	def test_lead_addresses_follow_through_a_contact_linking_both(self):
		saved = va.save_request(phone=CONVERTING_CALLER, key=KEY, name="VA Contact Path", address="9 Hill Rd", city="Chennai", pincode="600040")
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "VA Contact Path Customer", "customer_group": "Individual", "customer_type": "Individual",
			 "default_price_list": "Standard Selling", "gst_category": "Unregistered"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Contact", "first_name": "VA Contact Path",
			 "links": [{"link_doctype": "Customer", "link_name": customer.name}, {"link_doctype": "CRM Lead", "link_name": saved["lead"]}]}
		).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Dynamic Link", {"parenttype": "Address", "parent": saved["address"], "link_doctype": "Customer", "link_name": customer.name}))

	def _undecided_logs(self, customer):
		return frappe.get_all(
			"Error Log", filters={"method": ("like", f"Lead Address Link: could not decide the CRM Lead for Customer {customer}%")}, pluck="name"
		)

	def _delete_undecided_logs(self, customer):
		# Error Log lives in Frappe's separate log database, which commits on its
		# own - outside this test's rollback - so the rows are removed explicitly.
		for name in self._undecided_logs(customer):
			frappe.delete_doc("Error Log", name, ignore_permissions=True, force=True)

	def test_two_leads_on_the_customers_mobile_are_logged_not_linked(self):
		self._delete_undecided_logs("VA Twin Customer")
		self.addCleanup(self._delete_undecided_logs, "VA Twin Customer")
		first = va.save_request(phone=CONVERTING_CALLER, key=KEY, name="VA Twin One", address="1 Twin Rd", city="Chennai", pincode="600040")
		# A legacy duplicate the [BR-CRM-001] guard would refuse today - written directly.
		twin = self._lead("VA Twin Two", TWIN_SEED)
		frappe.db.set_value("CRM Lead", twin, "mobile_no", CONVERTING_CALLER)
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "VA Twin Customer", "customer_group": "Individual", "customer_type": "Individual",
			 "default_price_list": "Standard Selling", "gst_category": "Unregistered", "mobile_no": CONVERTING_CALLER}
		).insert(ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Dynamic Link", {"parenttype": "Address", "parent": first["address"], "link_doctype": "Customer"}))
		logs = self._undecided_logs(customer.name)
		self.assertEqual(len(logs), 1)
		# Error Log is in the log database - read it through the doctype API, not frappe.db.
		self.assertIn(first["lead"], frappe.get_all("Error Log", filters={"name": logs[0]}, pluck="error")[0])

		customer.save(ignore_permissions=True)
		self.assertEqual(len(self._undecided_logs(customer.name)), 1, "logged once, not on every save")

	def test_contact_linked_to_two_leads_is_logged_not_linked(self):
		self._delete_undecided_logs("VA Fork Customer")
		self.addCleanup(self._delete_undecided_logs, "VA Fork Customer")
		saved = va.save_request(phone=CONVERTING_CALLER, key=KEY, name="VA Two Lead Contact", address="3 Fork Rd", city="Chennai", pincode="600040")
		other = self._lead("VA Other Lead", OTHER_LEAD)
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "VA Fork Customer", "customer_group": "Individual", "customer_type": "Individual",
			 "default_price_list": "Standard Selling", "gst_category": "Unregistered"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Contact", "first_name": "VA Fork",
			 "links": [{"link_doctype": "Customer", "link_name": customer.name},
			           {"link_doctype": "CRM Lead", "link_name": saved["lead"]}, {"link_doctype": "CRM Lead", "link_name": other}]}
		).insert(ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Dynamic Link", {"parenttype": "Address", "parent": saved["address"], "link_doctype": "Customer"}))
		self.assertTrue(self._undecided_logs(customer.name))

	# --- where the shared key may be sent ------------------------------------

	def _api(self, method, http_method="POST", query=None, form=None, json_body=None, headers=None):
		"""
		Runs `method` the way /api/method/<method> does - a real werkzeug
		Request, Frappe's own make_form_dict (which drops the URL query string
		for a JSON body) and execute_cmd (whitelist + HTTP-method checks), as
		Guest - without the WSGI app's own connection and commit.
		"""
		from frappe.app import make_form_dict
		from frappe.handler import execute_cmd

		environ = EnvironBuilder(
			method=http_method, path=f"/api/method/{method}", query_string=query, data=form, json=json_body, headers=headers
		).get_environ()
		previous = (getattr(frappe.local, "request", None), frappe.local.form_dict)
		frappe.local.request = Request(environ)
		try:
			# Guest first: set_user resets form_dict, and a real request also
			# resolves its user before the arguments are built.
			frappe.set_user("Guest")
			make_form_dict(frappe.local.request)
			return execute_cmd(method)
		finally:
			frappe.set_user("Administrator")
			frappe.local.request, frappe.local.form_dict = previous

	KEY_METHODS = {
		"save_request": {"phone": BLOCKED, "name": "Key Test", "caller_type": "individual"},
		"upsert_quote": {"phone": BLOCKED, "items": json.dumps([{"item_code": PACK, "qty": 1}])},
		"set_caller_preferences": {"phone": BLOCKED, "preferences": json.dumps({"preferred_language": "ta"})},
	}

	def _ways(self, key):
		"""The four ways Sarvam's tools may send the key, each carrying `key`."""
		return {
			"form POST, key in URL": lambda m, a: self._api(m, query={"key": key}, form=a),
			"JSON POST, key in URL only": lambda m, a: self._api(m, query={"key": key}, json_body=a),
			"JSON POST, key in body only": lambda m, a: self._api(m, json_body={**a, "key": key}),
			"key in X-Webhook-Key header only": lambda m, a: self._api(m, json_body=a, headers={"X-Webhook-Key": key}),
		}

	def _counts(self):
		return {dt: frappe.db.count(dt) for dt in ("CRM Lead", "CRM Task", "CRM Deal", "Quotation")}

	def test_key_is_accepted_from_form_url_json_body_and_header(self):
		before = self._counts()
		for method, args in self.KEY_METHODS.items():
			for way, call in self._ways(KEY).items():
				with self.subTest(method=method, way=way):
					result = call(f"core_customizations.core_customizations.voice_agent.{method}", args)
					# Past the key check: the gate answered (blocked caller, so nothing is written).
					self.assertEqual((result["allowed"], result["reason"]), (False, "BLOCKED_LIST"))
		self.assertEqual(self._counts(), before)

	def test_wrong_or_missing_key_is_refused_everywhere(self):
		before = self._counts()
		for method, args in self.KEY_METHODS.items():
			cmd = f"core_customizations.core_customizations.voice_agent.{method}"
			for bad in ("wrong-key", ""):
				for way, call in self._ways(bad).items():
					with self.subTest(method=method, way=way, key=bad or "<empty>"), self.assertRaises(frappe.PermissionError):
						call(cmd, args)
			with self.subTest(method=method, way="no key at all"), self.assertRaises(frappe.PermissionError):
				self._api(cmd, json_body=args)
		self.assertEqual(self._counts(), before)

	def test_get_caller_context_with_key_in_url_still_works(self):
		result = self._api(
			"core_customizations.core_customizations.voice_agent.caller_context", http_method="GET", query={"key": KEY, "phone": LEAD_ONLY}
		)
		self.assertEqual(result["lead"]["name"], self.lead_only)

	def test_caller_gate_check_accepts_a_json_post_with_key_in_url(self):
		result = self._api("core_customizations.core_customizations.caller_gate.check", query={"key": KEY}, json_body={"phone": BLOCKED})
		self.assertEqual(result["reason"], "BLOCKED_LIST")

	def test_the_key_is_never_kept_for_logging(self):
		payload, headers = without_webhook_key({"key": KEY, "phone": BLOCKED}, {"X-Webhook-Key": KEY, "Content-Type": "application/json"})
		self.assertEqual(payload, {"phone": BLOCKED})
		self.assertEqual(headers, {"Content-Type": "application/json"})
		self.assertNotIn(KEY, json.dumps([payload, headers]))

	# --- category review warning only without a usable Customer group --------

	def _no_default_for(self, category):
		"""Mirror dev's edited settings: the category's rows exist but none is the default."""
		for row in frappe.get_single(SARVAM_SETTINGS_DOCTYPE).caller_categories:
			if row.category == category:
				frappe.db.set_value("Sarvam Caller Category", row.name, "is_default", 0)
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)

	def test_existing_customer_with_a_group_gets_no_category_warning(self):
		self._no_default_for("wholesale")
		for phone, caller_type in ((COMMERCIAL_CUSTOMER, "wholesale"), (CUSTOMER_ONLY, "retailer"), (CUSTOMER_ONLY, "no-such-category")):
			with self.subTest(phone=phone, caller_type=caller_type):
				result = va.save_request(phone=phone, key=KEY, caller_type=caller_type, notes="Repeat order")
				self.assertEqual(result["status"], "saved", result)
				self.assertFalse([w for w in result["warnings"] if w.startswith(("CUSTOMER_GROUP_NEEDS_REVIEW", "UNKNOWN_CATEGORY"))], result["warnings"])

	def test_customer_with_an_unmapped_group_still_gets_the_warning(self):
		frappe.db.set_value("Customer", self.commercial, "customer_group", "Government")  # no Caller Category row
		result = va.save_request(phone=COMMERCIAL_CUSTOMER, key=KEY, caller_type="retailer", notes="Order")
		self.assertIn("CUSTOMER_GROUP_NEEDS_REVIEW: retailer", result["warnings"])

	def test_new_caller_still_gets_the_category_warning(self):
		self._no_default_for("wholesale")
		result = va.save_request(phone=NEW_CALLER, key=KEY, name="VA Unit Wholesaler", caller_type="wholesale")
		self.assertIn("CUSTOMER_GROUP_NEEDS_REVIEW: wholesale", result["warnings"])

	# --- combined GST fields ------------------------------------------------

	def _assert_gst_fields(self, result, types):
		self.assertEqual(result["status"], "quoted", result)
		doc = frappe.get_doc("Quotation", result["quotation"])
		self.assertEqual(sorted(t["type"] for t in result["taxes"]), types)
		self.assertEqual(result["gst_percent"], 5.0)
		gst_rows = sum(t.tax_amount for t in doc.taxes if t.charge_type != "Actual")
		self.assertEqual(result["gst_amount"], flt(gst_rows, doc.precision("total_taxes_and_charges")))
		self.assertAlmostEqual(result["gst_amount"], doc.total_taxes_and_charges - result["shipping"], places=2)
		self.assertAlmostEqual(result["net_total"] + result["gst_amount"] + result["shipping"], doc.grand_total, places=2)
		return result

	def test_in_state_quote_has_combined_gst(self):
		result = self._assert_gst_fields(va.upsert_quote(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}]), ["CGST", "SGST"])
		self.assertEqual(result["gst_amount"], sum(t["amount"] for t in result["taxes"]))

	def test_out_of_state_quote_has_combined_gst(self):
		result = self._assert_gst_fields(va.upsert_quote(phone=LEAD_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}]), ["IGST"])
		self.assertEqual(result["gst_amount"], result["taxes"][0]["amount"])

	def test_save_request_quote_carries_the_combined_gst(self):
		result = va.save_request(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		self.assertEqual((result["quote"]["gst_percent"], result["quote"]["gst_amount"]), (5.0, sum(t["amount"] for t in result["quote"]["taxes"])))

	# --- call-ended transcript ------------------------------------------------

	def test_transcript_is_one_note_on_the_call_log(self):
		va.caller_context(phone=LEAD_ONLY, key=KEY, call_id="va-test-call-transcript")
		log = frappe.get_doc("CRM Call Log", "va-test-call-transcript")
		transcript = [{"role": "agent", "en_text": "Welcome to Sravi Enterprises."}, {"role": "user", "en_text": "I want <b>10</b> packs"}]
		first = va.save_transcript_note(log, transcript)
		again = va.save_transcript_note(log, json.dumps(transcript + [{"role": "agent", "en_text": "Saved."}]))
		self.assertEqual(first, again, "a redelivered webhook updates the same note")
		notes = frappe.get_all("FCRM Note", {"reference_doctype": "CRM Call Log", "reference_docname": log.name}, ["name", "title", "content"])
		self.assertEqual(len(notes), 1)
		self.assertTrue(notes[0].title.startswith("Call transcript: "))
		self.assertIn("<p>agent: Saved.</p>", notes[0].content)
		self.assertIn("&lt;b&gt;10&lt;/b&gt;", notes[0].content, "transcript text is escaped, not rendered as HTML")
		self.assertFalse(frappe.db.exists("Comment", {"reference_doctype": "CRM Call Log", "reference_name": log.name, "comment_type": "Comment"}))
		self.assertIsNone(va.save_transcript_note(log, None))

	# --- price list resolution [BR-CRM-006] -----------------------------------

	def _set_lists(self, customer, customer_list=None, group_list=None, settings_list="Standard Selling", category="individual"):
		"""Customer's own list, its group's list and the settings fallback for `category` (None = blank)."""
		frappe.db.set_value("Customer", customer, "default_price_list", customer_list)
		group = frappe.db.get_value("Customer", customer, "customer_group")
		frappe.db.set_value("Customer Group", group, "default_price_list", group_list)
		for row in frappe.get_single(SARVAM_SETTINGS_DOCTYPE).caller_categories:
			if row.category == category:
				frappe.db.set_value("Sarvam Caller Category", row.name, "price_list", settings_list if row.is_default or row.customer_group == group else row.price_list)
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)

	def _quote_both_ways(self, phone, items):
		"""Case 8: the same request through upsert_quote and through save_request's quote."""
		quote = va.upsert_quote(phone=phone, key=KEY, items=items)
		saved = va.save_request(phone=phone, key=KEY, items=items)["quote"]
		return {"upsert_quote": quote, "save_request": saved}

	def _assert_list(self, result, price_list, rate, source):
		self.assertEqual(result["status"], "quoted", result)
		self.assertEqual((result["price_list"], result["price_list_source"]), (price_list, source))
		self.assertEqual(result["items"][0]["rate"], rate)
		self.assertEqual(frappe.db.get_value("Quotation", result["quotation"], "selling_price_list"), price_list)

	def test_customer_list_wins_over_group_and_settings(self):
		self._set_lists(self.customer_only, "VA Unit Customer List", "VA Unit Group List", "Standard Selling")
		for way, result in self._quote_both_ways(CUSTOMER_ONLY, [{"item_code": PACK, "qty": 1}]).items():
			with self.subTest(way=way):
				self._assert_list(result, "VA Unit Customer List", 470, "customer")

	def test_falls_back_to_the_customer_group_list(self):
		self._set_lists(self.customer_only, None, "VA Unit Group List", "Standard Selling")
		for way, result in self._quote_both_ways(CUSTOMER_ONLY, [{"item_code": PACK, "qty": 1}]).items():
			with self.subTest(way=way):
				self._assert_list(result, "VA Unit Group List", 460, "customer_group")

	def test_falls_back_to_the_settings_list(self):
		self._set_lists(self.customer_only, None, None, "Standard Selling")
		for way, result in self._quote_both_ways(CUSTOMER_ONLY, [{"item_code": PACK, "qty": 1}]).items():
			with self.subTest(customer=True, way=way):
				self._assert_list(result, "Standard Selling", STANDARD_PACK_RATE, "settings")
		for way, result in self._quote_both_ways(LEAD_ONLY, [{"item_code": PACK, "qty": 1}]).items():
			with self.subTest(lead=True, way=way):
				self._assert_list(result, "Standard Selling", STANDARD_PACK_RATE, "settings")

	def test_no_list_anywhere_is_an_error_with_no_price(self):
		self._set_lists(self.commercial, None, None, None, category="wholesale")
		before = frappe.db.count("Quotation", {"party_name": self.commercial})
		result = va.upsert_quote(phone=COMMERCIAL_CUSTOMER, key=KEY, items=[{"item_code": LOOSE, "qty": 1}])
		self.assertEqual((result["status"], result["error"]), ("error", "NO_PRICE_LIST"))
		self.assertNotIn("items", result)
		saved = va.save_request(phone=COMMERCIAL_CUSTOMER, key=KEY, items=[{"item_code": LOOSE, "qty": 1}])
		self.assertIsNone(saved["quotation"])
		self.assertEqual(saved["quote"]["error"], "NO_PRICE_LIST")
		self.assertEqual(frappe.db.count("Quotation", {"party_name": self.commercial}), before, "nothing saved with a guessed rate")

	def test_changing_the_settings_list_does_not_change_a_customer_with_its_own_list(self):
		self._set_lists(self.customer_only, "VA Unit Customer List", None, "Standard Selling")
		before = va.upsert_quote(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		self._set_lists(self.customer_only, "VA Unit Customer List", None, "VA Unit Group List")
		after = va.upsert_quote(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		for result in (before, after):
			self._assert_list(result, "VA Unit Customer List", 470, "customer")

	def test_missing_pack_price_is_price_not_found_without_fallback(self):
		self._set_lists(self.customer_only, "VA Unit No Pack List", "VA Unit Group List", "Standard Selling")
		result = va.upsert_quote(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}])
		self.assertEqual((result["error"], result["price_list"], result["items"]), ("PRICE_NOT_FOUND", "VA Unit No Pack List", [PACK]))
		self.assertFalse(frappe.db.exists("Quotation", {"party_name": self.customer_only, "docstatus": 0}))

	def test_unusable_list_is_an_error_not_a_switch(self):
		for price_list, reason in (("VA Unit Disabled List", "is disabled"), ("VA Unit Buying List", "is not a selling price list"), ("VA Unit USD List", "is in USD, the quotation is in INR")):
			with self.subTest(price_list=price_list):
				self._set_lists(self.customer_only, price_list, "VA Unit Group List", "Standard Selling")
				result = va.upsert_quote(phone=CUSTOMER_ONLY, key=KEY, items=[{"item_code": PACK, "qty": 1}])
				self.assertEqual((result["error"], result["price_list"], result["reason"]), ("PRICE_LIST_UNUSABLE", price_list, reason))
		self.assertFalse(frappe.db.exists("Quotation", {"party_name": self.customer_only, "docstatus": 0}))

	def test_wholesale_customer_with_its_own_list(self):
		self._set_lists(self.commercial, "VA Unit Customer List", None, None, category="wholesale")
		no_items = va.save_request(phone=COMMERCIAL_CUSTOMER, key=KEY, notes="Call me about an order")
		self.assertIsNone(no_items["quotation"])
		self.assertFalse(frappe.db.exists("Quotation", {"party_name": self.commercial}), "no items -> no quote")
		with_items = va.save_request(phone=COMMERCIAL_CUSTOMER, key=KEY, items=[{"item_code": LOOSE, "qty": 2}])
		self._assert_list(with_items["quote"], "VA Unit Customer List", 40, "customer")
