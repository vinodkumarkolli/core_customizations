# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Tests for contact_lead_link - the background job that links a Contact to the
one CRM Lead on its number.

Guards the two wiring bugs it shipped with: the job was queued under a module
path that doesn't exist (`core_customizations.contact_lead_link`, so every job
failed with ModuleNotFoundError in the worker, logging nothing), and Contact's
`on_update` ran the Lead handler instead of the Contact one.

Runs inside a savepoint rolled back after each test; `frappe.enqueue` is
patched so nothing reaches the real queue.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from core_customizations.core_customizations import contact_lead_link as cll

LEAD_NUMBER = "+917000000301"
SECOND_ROW_NUMBER = "+917000000302"
TWIN_NUMBER = "+917000000303"


class TestContactLeadLink(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("contact_lead_link_test")
		self.enqueue = patch.object(frappe, "enqueue").start()
		self.addCleanup(patch.stopall)

	def tearDown(self):
		frappe.db.rollback(save_point="contact_lead_link_test")

	def _lead(self, name, mobile):
		return (
			frappe.get_doc(
				{"doctype": "CRM Lead", "first_name": name, "mobile_no": mobile, "status": "New", "lead_owner": "Administrator"}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _contact(self, name, *numbers):
		rows = [{"phone": n, "is_primary_mobile_no": int(i == 0)} for i, n in enumerate(numbers)]
		return frappe.get_doc({"doctype": "Contact", "first_name": name, "phone_nos": rows}).insert(ignore_permissions=True)

	def _queued_numbers(self):
		return {c.kwargs["number"] for c in self.enqueue.call_args_list if "contact_lead_link" in c.args[0]}

	def test_queued_job_path_imports_and_is_link_for_number(self):
		cll._queue({LEAD_NUMBER})
		method = self.enqueue.call_args.args[0]
		self.assertIs(frappe.get_attr(method), cll.link_for_number)

	def test_contact_on_update_runs_the_contact_handler(self):
		handlers = frappe.get_hooks("doc_events")["Contact"]["on_update"]
		self.assertIn("core_customizations.core_customizations.contact_lead_link.on_contact_update", handlers)
		self.assertNotIn("core_customizations.core_customizations.contact_lead_link.on_lead_update", handlers)

	def test_contact_save_queues_every_number_including_phone_rows(self):
		self._contact("CLL Two Numbers", LEAD_NUMBER, SECOND_ROW_NUMBER)
		self.assertEqual(self._queued_numbers(), {LEAD_NUMBER, SECOND_ROW_NUMBER})

	def test_job_links_the_contact_to_its_one_lead_without_requeueing(self):
		lead = self._lead("CLL Lead", LEAD_NUMBER)
		contact = self._contact("CLL Contact", LEAD_NUMBER)
		self.enqueue.reset_mock()

		cll.link_for_number(LEAD_NUMBER)

		links = frappe.get_all("Dynamic Link", {"parenttype": "Contact", "parent": contact.name, "link_doctype": "CRM Lead"}, pluck="link_name")
		self.assertEqual(links, [lead])
		self.assertEqual(self._queued_numbers(), set(), "the job's own save must not queue the job again")

	def test_job_never_guesses_between_two_leads(self):
		self._lead("CLL Twin One", TWIN_NUMBER)
		twin = self._lead("CLL Twin Two", "+917000000304")
		frappe.db.set_value("CRM Lead", twin, "mobile_no", TWIN_NUMBER)  # legacy duplicate
		contact = self._contact("CLL Twin Contact", TWIN_NUMBER)

		cll.link_for_number(TWIN_NUMBER)

		self.assertFalse(frappe.db.exists("Dynamic Link", {"parenttype": "Contact", "parent": contact.name, "link_doctype": "CRM Lead"}))
