# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Tests for callbacks_dashboard - the Callbacks workspace's Number Cards.

Counts are compared before/after creating Tasks, so live dev Tasks don't
matter; every test runs in a savepoint rolled back afterwards, and commits
are refused.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from core_customizations.core_customizations import callbacks_dashboard as cd
from core_customizations.core_customizations.caller_gate import get_automation_user
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

AUTOMATION_USER = "test-callbacks-automation@example.com"


class TestCallbacksDashboard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._commit_guard = patch.object(frappe.db, "commit", side_effect=AssertionError("must never commit"))
		cls._commit_guard.start()
		if not frappe.db.exists("User", AUTOMATION_USER):
			frappe.get_doc(
				{"doctype": "User", "email": AUTOMATION_USER, "first_name": "Callbacks Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.db.set_single_value(SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user", AUTOMATION_USER)

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		cls._commit_guard.stop()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("callbacks_dashboard_test")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="callbacks_dashboard_test")

	def _task(self, title, status="Todo", start_date=None, owner=AUTOMATION_USER):
		name = frappe.get_doc(
			{"doctype": "CRM Task", "title": title, "status": status, "start_date": start_date or nowdate(), "priority": "High"}
		).insert(ignore_permissions=True).name
		frappe.db.set_value("CRM Task", name, "owner", owner, update_modified=False)
		return name

	def _counts(self):
		return cd.callbacks_awaiting()["value"], cd.overdue_callbacks()["value"]

	def test_counts_only_open_voice_agent_callbacks(self):
		awaiting, overdue = self._counts()
		yesterday = add_days(nowdate(), -1)
		self._task("Callback: Today Caller")
		self._task("Callback: In Progress Caller", status="In Progress")
		self._task("Callback: Yesterday Caller", status="Backlog", start_date=yesterday)
		# Not counted: done/cancelled, made by staff, or not a callback.
		self._task("Callback: Done Caller", status="Done", start_date=yesterday)
		self._task("Callback: Cancelled Caller", status="Canceled")
		self._task("Callback: Typed By Staff", start_date=yesterday, owner="Administrator")
		self._task("Send brochure", start_date=yesterday)
		self.assertEqual(self._counts(), (awaiting + 3, overdue + 1))

	def test_a_postponed_callback_is_not_overdue(self):
		_, overdue = self._counts()
		self._task("Callback: Call Tomorrow", start_date=add_days(nowdate(), 1))
		self.assertEqual(self._counts()[1], overdue)

	def test_cards_open_the_task_report_view_with_the_same_filters(self):
		for card, overdue in ((cd.callbacks_awaiting(), False), (cd.overdue_callbacks(), True)):
			with self.subTest(overdue=overdue):
				self.assertEqual(card["route"], ["List", "CRM Task", "Report"])
				self.assertEqual(card["route_options"], cd.callback_filters(overdue=overdue))
				self.assertEqual(card["route_options"]["owner"], get_automation_user())
				self.assertEqual(card["route_options"]["title"], ["like", "Callback:%"])
				self.assertEqual(card["route_options"]["status"], ["in", ["Backlog", "Todo", "In Progress"]])
				self.assertEqual("start_date" in card["route_options"], overdue)
		count = len(frappe.get_list("CRM Task", filters=cd.callback_filters(), pluck="name", limit_page_length=0))
		self.assertEqual(cd.callbacks_awaiting()["value"], count, "the number is the Report View's row count")

	def test_blank_automation_user_falls_back_to_the_title(self):
		frappe.db.set_single_value(SARVAM_SETTINGS_DOCTYPE, "caller_gate_automation_user", None)
		self.assertNotIn("owner", cd.callback_filters())
		awaiting, _ = self._counts()
		self._task("Callback: Anyone", owner="Administrator")
		self.assertEqual(self._counts()[0], awaiting + 1)

	def test_desk_records_point_at_these_methods(self):
		for card, method in (("Callbacks Awaiting", "callbacks_awaiting"), ("Overdue Callbacks", "overdue_callbacks")):
			doc = frappe.get_doc("Number Card", card)
			self.assertEqual((doc.type, doc.method), ("Custom", f"core_customizations.core_customizations.callbacks_dashboard.{method}"))
		workspace = frappe.get_doc("Workspace", "Callbacks")
		self.assertEqual({c.number_card_name for c in workspace.number_cards}, {"Callbacks Awaiting", "Overdue Callbacks"})
