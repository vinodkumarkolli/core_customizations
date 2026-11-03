# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Tests for [BR-CRM-002] caller_gate:
1. evaluate()/last_10_digits()/is_blocked_number()/is_foreign_number() - the
   pure decision logic, exercised across every number spelling.
2. guard_caller_gate() - the CRM Lead validate hook, exercised end-to-end via
   real inserts, scoped to whichever user "Sarvam Voice Agent
   Settings".caller_gate_automation_user names.
3. get_permission_query_conditions_crm_lead() - the raw SQL fragment, run
   against a real row to confirm the regex/subquery actually filters.
4. The automation-user setting itself being unset disables the gate.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from core_customizations.core_customizations.caller_gate import (
	REASON_BLOCKED_LIST,
	REASON_FOREIGN_NUMBER,
	evaluate,
	get_permission_query_conditions_crm_lead,
	guard_caller_gate,
	last_10_digits,
	lookup_by_phone,
)
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

BLOCKED_SPELLINGS = [
	"+919840456658",
	"919840456658",
	"09840456658",
	"9840456658",
	"+91 98404 56658",
]

STAFF_USER = "Administrator"

# This test's own fixture user, standing in for whatever real integration
# user "Sarvam Voice Agent Settings".caller_gate_automation_user is set to
# in production - the setting is what caller_gate actually reads, so these
# tests configure it rather than importing a hardcoded user id.
AUTOMATION_USER = "test-caller-gate-automation@example.com"


class TestCallerGate(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", AUTOMATION_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": AUTOMATION_USER,
					"first_name": "Caller Gate Test Automation",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.delete_doc("User", AUTOMATION_USER, ignore_permissions=True, force=True)
		super().tearDownClass()

	def setUp(self):
		self._original_automation_user = frappe.db.get_single_value(
			SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user"
		)
		frappe.db.set_single_value(SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user", AUTOMATION_USER)

		frappe.db.delete("Blocked Contact", {"mobile_no": "9840456658"})
		self.blocked_caller = frappe.get_doc(
			{"doctype": "Blocked Contact", "mobile_no": "9840456658", "enabled": 1, "reason": "test"}
		).insert(ignore_permissions=True)
		self._created_leads = []

	def tearDown(self):
		frappe.set_user(STAFF_USER)
		frappe.db.set_single_value(
			SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user", self._original_automation_user
		)
		for lead in self._created_leads:
			frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
		frappe.delete_doc("Blocked Contact", self.blocked_caller.name, ignore_permissions=True, force=True)

	def _new_lead(self, mobile_no, lead_name="Caller Gate Test"):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": lead_name,
				"lead_name": lead_name,
				"mobile_no": mobile_no,
				"status": "New",
			}
		)
		return doc

	# --- evaluate() / is_blocked_number() across every spelling -----------

	def test_blocked_number_in_every_spelling_is_rejected(self):
		for spelling in BLOCKED_SPELLINGS:
			with self.subTest(spelling=spelling):
				result = evaluate(spelling)
				self.assertFalse(result["allowed"])
				self.assertEqual(result["reason"], REASON_BLOCKED_LIST)

	def test_last_10_digits_normalises_every_spelling_the_same(self):
		for spelling in BLOCKED_SPELLINGS:
			with self.subTest(spelling=spelling):
				self.assertEqual(last_10_digits(spelling), "9840456658")

	# --- foreign numbers ----------------------------------------------------

	def test_foreign_number_is_rejected(self):
		for foreign in ("+14155552671", "+442071838750"):
			with self.subTest(foreign=foreign):
				result = evaluate(foreign)
				self.assertFalse(result["allowed"])
				self.assertEqual(result["reason"], REASON_FOREIGN_NUMBER)

	# --- blank / normal Indian number ---------------------------------------

	def test_blank_number_is_allowed(self):
		for blank in (None, "", "   "):
			with self.subTest(blank=repr(blank)):
				result = evaluate(blank)
				self.assertTrue(result["allowed"])
				self.assertIsNone(result["reason"])

	def test_normal_indian_number_is_allowed(self):
		result = evaluate("+919876543210")
		self.assertTrue(result["allowed"])
		self.assertIsNone(result["reason"])

	# --- disabled Blocked Contact row -----------------------------------------

	def test_disabled_blocked_caller_row_is_allowed(self):
		self.blocked_caller.enabled = 0
		self.blocked_caller.save(ignore_permissions=True)
		result = evaluate("+919840456658")
		self.assertTrue(result["allowed"])

	def test_blocked_caller_name_matches_normalised_mobile_no(self):
		# autoname (field:mobile_no) resolves `name` before `validate()`
		# normalises the field - before_insert must normalise first, or
		# a row typed with spaces/prefix ends up named the raw string.
		frappe.db.delete("Blocked Contact", {"mobile_no": "9000022222"})
		doc = frappe.get_doc(
			{"doctype": "Blocked Contact", "mobile_no": "+91 90000 22222", "enabled": 1}
		).insert(ignore_permissions=True)
		try:
			self.assertEqual(doc.name, "9000022222")
			self.assertEqual(doc.mobile_no, "9000022222")
		finally:
			frappe.delete_doc("Blocked Contact", doc.name, ignore_permissions=True, force=True)

	# --- guard_caller_gate(): end-to-end via a real CRM Lead insert --------

	def test_automation_user_cannot_create_lead_for_blocked_number(self):
		frappe.set_user(AUTOMATION_USER)
		doc = self._new_lead("+919840456658")
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.insert(ignore_permissions=True)
		self.assertIn("CALLER_BLOCKED: reason=BLOCKED_LIST", str(ctx.exception))

	def test_automation_user_cannot_create_lead_for_foreign_number(self):
		frappe.set_user(AUTOMATION_USER)
		doc = self._new_lead("+14155552671")
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.insert(ignore_permissions=True)
		self.assertIn("CALLER_BLOCKED: reason=FOREIGN_NUMBER", str(ctx.exception))

	def test_staff_user_on_blocked_number_is_allowed(self):
		frappe.set_user(STAFF_USER)
		doc = self._new_lead("+919840456658", lead_name="Caller Gate Staff Test")
		doc.insert(ignore_permissions=True)
		self._created_leads.append(doc.name)

	def test_bypass_flag_overrides_the_guard(self):
		frappe.set_user(AUTOMATION_USER)
		doc = self._new_lead("+919840456658", lead_name="Caller Gate Bypass Test")
		doc.flags.ignore_caller_gate = True
		doc.insert(ignore_permissions=True)
		self._created_leads.append(doc.name)

	def test_guard_is_a_noop_without_a_resolvable_phone(self):
		# Calling the hook function directly (not via a real insert) on a
		# doc with no phone at all must not raise - there is nothing to judge.
		doc = frappe.new_doc("CRM Lead")
		doc.lead_name = "No Phone"
		frappe.set_user(AUTOMATION_USER)
		guard_caller_gate(doc)  # should not raise

	def test_gate_is_disabled_when_automation_user_unset(self):
		frappe.db.set_single_value(SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user", None)
		frappe.set_user(AUTOMATION_USER)
		doc = self._new_lead("+919840456658", lead_name="Caller Gate Unset Setting Test")
		doc.insert(ignore_permissions=True)
		self._created_leads.append(doc.name)
		self.assertEqual(get_permission_query_conditions_crm_lead(user=AUTOMATION_USER), "")

	# --- permission_query_conditions: the raw SQL actually filters ---------

	def test_permission_query_condition_is_empty_for_non_automation_user(self):
		frappe.set_user(STAFF_USER)
		self.assertEqual(get_permission_query_conditions_crm_lead(), "")

	def test_permission_query_condition_filters_a_blocked_row_in_sql(self):
		condition = get_permission_query_conditions_crm_lead(user=AUTOMATION_USER)
		self.assertTrue(condition)
		rows = frappe.db.sql(
			f"""
			select mobile_no from (
				select '+919840456658' as mobile_no
				union all select '+919876543210'
				union all select ''
				union all select '+14155552671'
			) as `tabCRM Lead`
			where {condition}
			""",
		)
		returned = {r[0] for r in rows}
		self.assertEqual(returned, {"+919876543210", ""})


# A plain Sales User who owns nothing - standing in for the real
# automation.crm@sravie.in account's own Sales User role, to prove
# lookup_by_phone's permission bypass is scoped to the configured
# automation user and does not leak into a broader hole for anyone else.
OTHER_SALES_USER = "test-caller-gate-other-sales-user@example.com"
LEAD_OWNER = "test-caller-gate-lead-owner@example.com"


class TestLookupByPhone(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", AUTOMATION_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": AUTOMATION_USER,
					"first_name": "Lookup Test Automation",
					"send_welcome_email": 0,
					# Mirrors production: automation.crm@sravie.in holds the
					# Sales User role - Contact read requires it (or
					# if_owner), and CRM Lead read requires it too, before
					# org_hierarchy narrows it further to owned/assigned Leads.
					"user_type": "System User",
					"roles": [{"role": "Sales User"}],
				}
			).insert(ignore_permissions=True)
		for email, first_name in (
			(OTHER_SALES_USER, "Other Sales User"),
			(LEAD_OWNER, "Lead Owner"),
		):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": first_name,
						"send_welcome_email": 0,
						"user_type": "System User",
						"roles": [{"role": "Sales User"}],
					}
				).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.delete_doc("User", AUTOMATION_USER, ignore_permissions=True, force=True)
		frappe.delete_doc("User", OTHER_SALES_USER, ignore_permissions=True, force=True)
		frappe.delete_doc("User", LEAD_OWNER, ignore_permissions=True, force=True)
		super().tearDownClass()

	def setUp(self):
		frappe.set_user(STAFF_USER)
		self._original_automation_user = frappe.db.get_single_value(
			SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user"
		)
		frappe.db.set_single_value(SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user", AUTOMATION_USER)

		frappe.db.delete("Blocked Contact", {"mobile_no": "9812500001"})
		frappe.db.delete("CRM Lead", {"mobile_no": "+919812500002"})
		frappe.db.delete("Contact", {"mobile_no": "+919812500003"})

		self.lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Lookup Test Lead",
				"lead_name": "Lookup Test Lead",
				"mobile_no": "+919812500002",
				"status": "New",
				"lead_owner": LEAD_OWNER,
			}
		).insert(ignore_permissions=True)
		self.contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Lookup Test Contact",
				# Contact derives its own mobile_no from the primary row in
				# phone_nos (Contact.validate's set_primary("mobile_no")) -
				# setting the top-level field alone is discarded.
				"phone_nos": [{"phone": "+919812500003", "is_primary_mobile_no": 1}],
			}
		).insert(ignore_permissions=True)
		self._created_customers = []

	def tearDown(self):
		frappe.set_user(STAFF_USER)
		frappe.db.set_single_value(
			SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user", self._original_automation_user
		)
		frappe.delete_doc("CRM Lead", self.lead.name, ignore_permissions=True, force=True)
		frappe.delete_doc("Contact", self.contact.name, ignore_permissions=True, force=True)
		frappe.db.delete("Blocked Contact", {"mobile_no": "9812500001"})
		for customer in self._created_customers:
			frappe.delete_doc("Customer", customer, ignore_permissions=True, force=True)

	def test_blank_phone_returns_none_without_querying(self):
		self.assertEqual(lookup_by_phone(""), {"lead": None, "contact": None, "customer": None})
		self.assertEqual(lookup_by_phone(None), {"lead": None, "contact": None, "customer": None})

	def test_no_match_returns_none(self):
		frappe.set_user(AUTOMATION_USER)
		self.assertEqual(
			lookup_by_phone("+919999999999"), {"lead": None, "contact": None, "customer": None}
		)

	def test_automation_user_finds_lead_it_does_not_own(self):
		frappe.set_user(AUTOMATION_USER)
		result = lookup_by_phone("+919812500002")
		self.assertIsNotNone(result["lead"])
		self.assertEqual(result["lead"]["name"], self.lead.name)

	def test_automation_user_finds_contact(self):
		frappe.set_user(AUTOMATION_USER)
		result = lookup_by_phone("+919812500003")
		self.assertIsNotNone(result["contact"])
		self.assertEqual(result["contact"]["name"], self.contact.name)

	def test_resolves_customer_via_contact_dynamic_link(self):
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "Lookup Test Customer Via Link", "customer_type": "Company", "customer_group": "Commercial", "default_price_list": "Distributor Pricelist 40.50"}
		).insert(ignore_permissions=True)
		self._created_customers.append(customer.name)
		self.contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})
		self.contact.save(ignore_permissions=True)

		frappe.set_user(AUTOMATION_USER)
		result = lookup_by_phone("+919812500003")
		self.assertIsNotNone(result["customer"])
		self.assertEqual(result["customer"]["name"], customer.name)

	def test_resolves_customer_via_lead_organization(self):
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "Lookup Test Customer Via Org", "customer_type": "Company", "customer_group": "Commercial", "default_price_list": "Distributor Pricelist 40.50"}
		).insert(ignore_permissions=True)
		self._created_customers.append(customer.name)
		self.lead.organization = customer.customer_name
		self.lead.save(ignore_permissions=True)

		frappe.set_user(AUTOMATION_USER)
		result = lookup_by_phone("+919812500002")
		self.assertIsNotNone(result["customer"])
		self.assertEqual(result["customer"]["name"], customer.name)

	def test_other_sales_user_does_not_see_a_lead_it_does_not_own(self):
		# Proves the ignore_permissions bypass is scoped to AUTOMATION_USER
		# only - org_hierarchy's ownership restriction still applies to any
		# other Sales User calling the same whitelisted method.
		frappe.set_user(OTHER_SALES_USER)
		result = lookup_by_phone("+919812500002")
		self.assertIsNone(result["lead"])

	def test_automation_user_blocked_number_raises(self):
		frappe.get_doc(
			{"doctype": "Blocked Contact", "mobile_no": "9812500001", "enabled": 1, "reason": "test"}
		).insert(ignore_permissions=True)
		frappe.set_user(AUTOMATION_USER)
		with self.assertRaises(frappe.ValidationError) as ctx:
			lookup_by_phone("+919812500001")
		self.assertIn("CALLER_BLOCKED: reason=BLOCKED_LIST", str(ctx.exception))

	def test_automation_user_foreign_number_raises(self):
		frappe.set_user(AUTOMATION_USER)
		with self.assertRaises(frappe.ValidationError) as ctx:
			lookup_by_phone("+14155552671")
		self.assertIn("CALLER_BLOCKED: reason=FOREIGN_NUMBER", str(ctx.exception))
