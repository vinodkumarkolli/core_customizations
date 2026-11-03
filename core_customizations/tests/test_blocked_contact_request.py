# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Tests for [BR-CRM-003] the Blocked Contact Request escalation/approval
process:
1. escalate_lead_for_blocking() - a Sales User raising and submitting a
   request from a CRM Lead.
2. The "Blocked Contact Escalation" Workflow's Approve/Reject transitions,
   driven through frappe.model.workflow.apply_workflow (the same engine the
   Desk UI's workflow buttons use), exercising
   handle_blocked_contact_request_update/_cancel end-to-end.
3. Guardrails: no mobile number, duplicate open escalations, reusing an
   existing (possibly disabled) Blocked Contact instead of erroring.
"""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests.utils import FrappeTestCase

from core_customizations.core_customizations.caller_gate import escalate_lead_for_blocking

SALES_USER = "test-blocked-contact-sales-user@example.com"
SYSTEM_MANAGER = "Administrator"


class TestBlockedContactRequest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", SALES_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": SALES_USER,
					"first_name": "Blocked Contact Test Sales User",
					"send_welcome_email": 0,
					"user_type": "System User",
					"roles": [{"role": "Sales User"}],
				}
			).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.delete_doc("User", SALES_USER, ignore_permissions=True, force=True)
		super().tearDownClass()

	def setUp(self):
		frappe.set_user(SYSTEM_MANAGER)
		self._created_requests = []
		self._created_leads = []
		self._created_blocked_contacts = []

	def tearDown(self):
		frappe.set_user(SYSTEM_MANAGER)
		for request in self._created_requests:
			frappe.db.set_value("Blocked Contact Request", request, "docstatus", 0)
			frappe.delete_doc("Blocked Contact Request", request, ignore_permissions=True, force=True)
		for lead in self._created_leads:
			frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
		for blocked in self._created_blocked_contacts:
			frappe.delete_doc("Blocked Contact", blocked, ignore_permissions=True, force=True)

	def _new_lead(self, mobile_no, lead_name="BCR Test Lead"):
		# crm's own org_hierarchy permission model (CRM Lead's
		# permission_query_conditions/has_permission) only lets a Sales
		# User read a Lead they own - unrelated to this feature, but
		# escalate_lead_for_blocking checks frappe.has_permission first,
		# so the test fixture Lead must be owned by SALES_USER.
		doc = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": lead_name,
				"lead_name": lead_name,
				"mobile_no": mobile_no,
				"status": "New",
				"lead_owner": SALES_USER,
			}
		).insert(ignore_permissions=True)
		self._created_leads.append(doc.name)
		return doc

	def _escalate(self, lead_name, reason="test escalation"):
		frappe.set_user(SALES_USER)
		try:
			request_name = escalate_lead_for_blocking(lead_name, reason)
		finally:
			frappe.set_user(SYSTEM_MANAGER)
		self._created_requests.append(request_name)
		return frappe.get_doc("Blocked Contact Request", request_name)

	# --- escalation itself --------------------------------------------------

	def test_sales_user_can_escalate_a_lead(self):
		lead = self._new_lead("+919812300001")
		request = self._escalate(lead.name)
		self.assertEqual(request.workflow_state, "Pending")
		self.assertEqual(request.docstatus, 1)
		self.assertEqual(request.mobile_no, "+919812300001")
		self.assertEqual(request.lead_name, lead.lead_name)
		self.assertFalse(request.blocked_contact)

	def test_escalating_lead_without_mobile_no_fails(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "No Phone",
				"lead_name": "No Phone",
				"status": "New",
				"lead_owner": SALES_USER,
			}
		).insert(ignore_permissions=True)
		self._created_leads.append(lead.name)

		frappe.set_user(SALES_USER)
		try:
			with self.assertRaises(frappe.ValidationError):
				escalate_lead_for_blocking(lead.name, "test")
		finally:
			frappe.set_user(SYSTEM_MANAGER)

	def test_escalating_without_reason_fails(self):
		lead = self._new_lead("+919812300002")
		frappe.set_user(SALES_USER)
		try:
			with self.assertRaises(frappe.ValidationError):
				escalate_lead_for_blocking(lead.name, "   ")
		finally:
			frappe.set_user(SYSTEM_MANAGER)

	def test_duplicate_open_escalation_is_refused(self):
		lead = self._new_lead("+919812300003")
		self._escalate(lead.name)
		with self.assertRaises(frappe.ValidationError):
			self._escalate(lead.name)

	# --- Approve: creates the Blocked Contact -------------------------------

	def test_approving_creates_blocked_contact(self):
		lead = self._new_lead("+919812300004")
		request = self._escalate(lead.name, reason="repeat nuisance calls")

		frappe.set_user(SYSTEM_MANAGER)
		apply_workflow(request, "Approve")
		request.reload()

		self.assertEqual(request.workflow_state, "Approved")
		self.assertTrue(request.blocked_contact)
		self._created_blocked_contacts.append(request.blocked_contact)

		blocked = frappe.get_doc("Blocked Contact", request.blocked_contact)
		self.assertEqual(blocked.mobile_no, "9812300004")
		self.assertEqual(blocked.reason, "repeat nuisance calls")
		self.assertEqual(blocked.enabled, 1)

	def test_approving_reuses_existing_disabled_blocked_contact(self):
		existing = frappe.get_doc(
			{"doctype": "Blocked Contact", "mobile_no": "9812300005", "enabled": 0, "reason": "old reason"}
		).insert(ignore_permissions=True)
		self._created_blocked_contacts.append(existing.name)

		lead = self._new_lead("+919812300005")
		request = self._escalate(lead.name)

		frappe.set_user(SYSTEM_MANAGER)
		apply_workflow(request, "Approve")
		request.reload()

		self.assertEqual(request.blocked_contact, existing.name)
		existing.reload()
		self.assertEqual(existing.enabled, 1)
		self.assertEqual(existing.reason, "old reason")  # not overwritten by the new escalation

	# --- Reject: no Blocked Contact, or disables an already-Approved one ----

	def test_rejecting_a_pending_request_creates_no_blocked_contact(self):
		lead = self._new_lead("+919812300006")
		request = self._escalate(lead.name)

		frappe.set_user(SYSTEM_MANAGER)
		apply_workflow(request, "Reject")
		request.reload()

		self.assertEqual(request.workflow_state, "Rejected")
		self.assertFalse(request.blocked_contact)
		self.assertFalse(frappe.db.exists("Blocked Contact", {"mobile_no": "9812300006"}))

	def test_rejecting_an_approved_request_disables_its_blocked_contact(self):
		lead = self._new_lead("+919812300007")
		request = self._escalate(lead.name)

		frappe.set_user(SYSTEM_MANAGER)
		apply_workflow(request, "Approve")
		request.reload()
		self._created_blocked_contacts.append(request.blocked_contact)

		apply_workflow(request, "Reject")
		request.reload()

		self.assertEqual(request.workflow_state, "Rejected")
		blocked = frappe.get_doc("Blocked Contact", request.blocked_contact)
		self.assertEqual(blocked.enabled, 0)
