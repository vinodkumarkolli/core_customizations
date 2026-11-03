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

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import set_encrypted_password

from core_customizations.core_customizations import voice_agent as va
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

KEY = "test-voice-agent-key"
AUTOMATION_USER = "test-voice-agent-automation@example.com"
COMPANY = "Sravi Enterprises - Kolapakkam"
PACK = "SASB-50INR-PACK-10"

# Test-only numbers (none exist on the site - asserted in setUpClass).
BLOCKED = "+917000000101"
FOREIGN = "+14155552671"
UNKNOWN = "+917000000102"
LEAD_ONLY = "+917000000103"
CUSTOMER_ONLY = "+917000000104"
LEAD_AND_CUSTOMER = "+917000000105"
LEGACY_SPACED_STORED = "70000 00106"  # how the legacy row is stored
LEGACY_SPACED_CALLER = "+917000000106"  # how Sarvam reports the caller
COMMERCIAL_CUSTOMER = "+917000000107"
NEW_CALLER = "+917000000108"

TEST_NUMBERS = [BLOCKED, UNKNOWN, LEAD_ONLY, CUSTOMER_ONLY, LEAD_AND_CUSTOMER, LEGACY_SPACED_CALLER, COMMERCIAL_CUSTOMER, NEW_CALLER]


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
		for number in TEST_NUMBERS:
			last10 = number[-10:]
			assert not frappe.db.sql(
				"select name from `tabCRM Lead` where right(regexp_replace(ifnull(mobile_no,''),'[^0-9]',''),10)=%s",
				last10,
			), f"{number} already used on this site"

		if not frappe.db.exists("User", AUTOMATION_USER):
			user = frappe.get_doc(
				{"doctype": "User", "email": AUTOMATION_USER, "first_name": "Voice Agent Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")

		# Written inside the test transaction - the class rollback restores the
		# site's own secret, so it is never read, copied or rewritten here.
		set_encrypted_password(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE, KEY, "webhook_secret")
		frappe.db.set_single_value(SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user", AUTOMATION_USER)
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)

		frappe.get_doc({"doctype": "Blocked Contact", "mobile_no": BLOCKED[-10:], "enabled": 1, "reason": "test"}).insert(
			ignore_permissions=True
		)

		cls.lead_only = cls._lead("VA Lead Only", LEAD_ONLY, category="individual", address="Address: 12 Kukatpally, Hyderabad 500072")
		cls.lead_with_customer = cls._lead("VA Lead And Customer", LEAD_AND_CUSTOMER, organization="VA Test Individual Customer")
		legacy = cls._lead("VA Legacy Spaced", LEGACY_SPACED_CALLER)
		# Bypass before_validate normalisation - this is what a pre-hook row looks like.
		frappe.db.set_value("CRM Lead", legacy, "mobile_no", LEGACY_SPACED_STORED)
		cls.legacy_lead = legacy

		cls.customer_only = cls._customer("VA Test Individual Customer", "Individual", CUSTOMER_ONLY)
		cls.commercial = cls._customer("VA Test Commercial Customer", "Commercial", COMMERCIAL_CUSTOMER)

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
	def _customer(cls, name, group, mobile):
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
		for spelling in (LEGACY_SPACED_CALLER, "917000000106", "07000000106", "7000000106", "+91 70000-00106"):
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
