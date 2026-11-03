# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Tests for caller_gate.check's `phone` key: a real number comes back as +91
and ten digits; a SHA-256 hash of the E.164 number is looked up among
Leads, Contacts and Customers; anything else is "".

Every test runs in a savepoint rolled back afterwards, and commits are refused.
"""

import hashlib
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import set_encrypted_password

from core_customizations.core_customizations.caller_gate import check
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

KEY = "test-check-phone-key"
LEAD_NUMBER = "+917000001201"
CONTACT_ROW_NUMBER = "+917000001202"
CUSTOMER_NUMBER = "+917000001203"
BLOCKED_NUMBER = "+917000001204"
NOBODY = "+917000001299"


def sha(number):
	return hashlib.sha256(number.encode()).hexdigest()


class TestCheckReturnsPhone(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._commit_guard = patch.object(frappe.db, "commit", side_effect=AssertionError("must never commit"))
		cls._commit_guard.start()
		for number in (LEAD_NUMBER, CONTACT_ROW_NUMBER, CUSTOMER_NUMBER, BLOCKED_NUMBER, NOBODY):
			assert not frappe.db.sql(
				"""select 1 from `tabCRM Lead` where right(regexp_replace(ifnull(mobile_no,''),'[^0-9]',''),10)=%(n)s
				   union select 1 from `tabContact Phone` where right(regexp_replace(ifnull(phone,''),'[^0-9]',''),10)=%(n)s
				   union select 1 from `tabCustomer` where right(regexp_replace(ifnull(mobile_no,''),'[^0-9]',''),10)=%(n)s""",
				{"n": number[-10:]},
			), f"{number} already used on this site"
		set_encrypted_password(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE, KEY, "webhook_secret")
		frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Check Phone Lead", "mobile_no": LEAD_NUMBER, "status": "New", "lead_owner": "Administrator"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Contact", "first_name": "Check Phone Contact",
			 "phone_nos": [{"phone": "+91 99999 00000", "is_primary_mobile_no": 1}, {"phone": "70000 01202"}]}
		).insert(ignore_permissions=True)
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "Check Phone Customer", "customer_group": "Individual",
			 "customer_type": "Individual", "default_price_list": "Standard Selling", "gst_category": "Unregistered"}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Customer", customer.name, "mobile_no", "7000001203")
		frappe.get_doc({"doctype": "Blocked Contact", "mobile_no": BLOCKED_NUMBER[-10:], "enabled": 1, "reason": "test"}).insert(
			ignore_permissions=True
		)

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		cls._commit_guard.stop()
		super().tearDownClass()

	def _check(self, phone):
		return check(phone=phone, key=KEY)

	def test_real_number_is_returned_normalised(self):
		for spelling in ("+919876543210", "919876543210", "9876543210", "09876543210", "+91 98765-43210", " 98765 43210 "):
			with self.subTest(spelling=spelling):
				result = self._check(spelling)
				self.assertEqual((result["allowed"], result["phone"]), (True, "+919876543210"))

	def test_hash_is_looked_up_on_leads_contacts_and_customers(self):
		for number in (LEAD_NUMBER, CONTACT_ROW_NUMBER, CUSTOMER_NUMBER):
			for digest in (sha(number), sha(number).upper()):
				with self.subTest(number=number, upper=digest.isupper()):
					result = self._check(digest)
					self.assertEqual((result["allowed"], result["reason"], result["phone"]), (True, None, number))

	def test_unmatched_hash_and_blank_return_empty_phone(self):
		for value in (sha(NOBODY), None, "", "   "):
			with self.subTest(value=value):
				result = self._check(value)
				self.assertEqual((result["allowed"], result["phone"]), (True, ""))

	def test_blocked_caller_is_refused_by_number_and_by_hash(self):
		for value in (BLOCKED_NUMBER, sha(BLOCKED_NUMBER)):
			with self.subTest(value=value):
				result = self._check(value)
				self.assertEqual((result["allowed"], result["reason"], result["phone"]), (False, "BLOCKED_LIST", ""))

	def test_foreign_and_junk_numbers_return_empty_phone(self):
		for value in ("+14155552671", "12345", "04423456789", "not a number", "abc123" * 10):
			with self.subTest(value=value):
				self.assertEqual(self._check(value)["phone"], "")
		self.assertEqual(self._check("+14155552671")["reason"], "FOREIGN_NUMBER")

	def test_existing_keys_are_unchanged(self):
		self.assertEqual(set(self._check("+919876543210")), {"allowed", "reason", "message", "phone"})
		with self.assertRaises(frappe.PermissionError):
			check(phone="+919876543210", key="wrong")
