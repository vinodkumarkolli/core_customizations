# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Tests for the voice agent's transfer routing [BR-TEL-006] - transfer_target
with a named executive, sticky agent, round robin and the busy ledger
(Sarvam Transfer Attempt), closed by the call-end webhook.

The executives and transfer window are pinned to test
values inside the class's transaction, every Transfer Attempt on the site is
deleted inside it (so the round-robin pointer starts clean), and each test
runs in a savepoint rolled back afterwards. Nothing may commit -
`frappe.db.commit` is patched to fail for the whole class.
"""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime
from frappe.utils.password import set_encrypted_password

from core_customizations.core_customizations import voice_agent as va
from core_customizations.core_customizations.sarvam_telephony import SARVAM_SETTINGS_DOCTYPE

KEY = "test-voice-agent-routing-key"
AUTOMATION_USER = "test-va-routing-automation@example.com"
ATTEMPT = va.ATTEMPT_DOCTYPE

# Executives: (name, number, user, aliases) - test-only numbers and users.
EXECUTIVES = [
	("Vinod", "+917000001291", "test-va-exec-vinod@example.com", ""),
	("Kalpana", "+917000001292", "test-va-exec-kalpana@example.com", "Kalpa, Kalpana Muthu"),
	("Sravya", "+917000001293", "test-va-exec-sravya@example.com", ""),
]
CALLER_A = "+917000001201"
CALLER_B = "+917000001202"
CALLER_OWNED = "+917000001203"  # lead owned by Kalpana's user
UNKNOWN = "+917000001209"
BLOCKED = "+917000001210"
TUESDAY_11 = datetime(2026, 11, 3, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


class TestVoiceAgentRouting(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._commit_guard = patch.object(frappe.db, "commit", side_effect=AssertionError("must never commit"))
		cls._commit_guard.start()
		for number in (CALLER_A, CALLER_B, CALLER_OWNED, UNKNOWN, BLOCKED):
			assert not frappe.db.sql(
				"select name from `tabCRM Lead` where right(regexp_replace(ifnull(mobile_no,''),'[^0-9]',''),10)=%s "
				"union select parent from `tabContact Phone` where right(regexp_replace(ifnull(phone,''),'[^0-9]',''),10)=%s",
				(number[-10:], number[-10:]),
			), f"{number} already used on this site"

		for email in [AUTOMATION_USER] + [e[2] for e in EXECUTIVES]:
			if not frappe.db.exists("User", email):
				user = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0})
				user.insert(ignore_permissions=True)
				user.add_roles("Sales User")

		set_encrypted_password(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE, KEY, "webhook_secret")
		settings = frappe.get_single(SARVAM_SETTINGS_DOCTYPE)
		settings.caller_gate_automation_user = AUTOMATION_USER
		settings.update(
			{
				"transfer_start_time": "10:00:00",
				"transfer_end_time": "20:00:00",
				"transfer_days": "Mon,Tue,Wed,Thu,Fri,Sat",
				"transfer_timezone": "Asia/Kolkata",
				"transfer_known_callers_only": 1,
				"sticky_agent": 0,
				"busy_timeout_minutes": 15,
			}
		)
		settings.transfer_executives = []
		for name, phone, user, aliases in EXECUTIVES:
			settings.append("transfer_executives", {"executive_name": name, "phone": phone, "user": user, "aliases": aliases, "enabled": 1})
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)

		frappe.db.delete(ATTEMPT)
		frappe.get_doc({"doctype": "Blocked Contact", "mobile_no": BLOCKED[-10:], "enabled": 1, "reason": "test"}).insert(ignore_permissions=True)
		cls.lead_a = cls._lead("VA Route A", CALLER_A)
		cls.lead_b = cls._lead("VA Route B", CALLER_B)
		cls.lead_owned = cls._lead("VA Route Owned", CALLER_OWNED, owner=EXECUTIVES[1][2])

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		cls._commit_guard.stop()
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)
		super().tearDownClass()

	@classmethod
	def _lead(cls, name, mobile, category=None, address=None, owner="Administrator"):
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Lead", "first_name": name, "mobile_no": mobile, "status": "New", "lead_owner": owner,
					"custom_caller_category": category, "company_description": address,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("va_routing_test")
		self._calls = 0

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="va_routing_test")
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)
		frappe.local.flags.commit = False

	# --- helpers ------------------------------------------------------------

	def _transfer(self, phone=CALLER_A, executive=None, interaction_id=None, when=TUESDAY_11):
		self._calls += 1
		interaction_id = interaction_id or f"va-route-{self._testMethodName}-{self._calls}"
		with patch.object(va, "_now", lambda tz: when.astimezone(tz)):
			return va.transfer_target(phone=phone, key=KEY, executive=executive, interaction_id=interaction_id)

	def _set(self, **values):
		frappe.db.set_single_value(SARVAM_SETTINGS_DOCTYPE, values)
		frappe.clear_document_cache(SARVAM_SETTINGS_DOCTYPE, SARVAM_SETTINGS_DOCTYPE)

	def _executive_row(self, name):
		return frappe.db.get_value(va.EXECUTIVE_DOCTYPE, {"parent": SARVAM_SETTINGS_DOCTYPE, "executive_name": name}, "name")

	def _on_break(self, name, value=1):
		frappe.db.set_value(va.EXECUTIVE_DOCTYPE, self._executive_row(name), "on_break", value)

	def _make_busy(self, name):
		"""Routes a call to `name` (named request from a known caller) and leaves it open."""
		result = self._transfer(CALLER_B, executive=name)
		self.assertEqual(result["executive"], name, result)
		return result

	def _end(self, interaction_id, phone=CALLER_A, transferred=None):
		variables = {"call_summary": "Caller asked for a person."}
		if transferred is not None:
			variables["transferred"] = transferred
		return va.record_inbound_call(
			{
				"interaction_id": interaction_id, "user_phone_number": phone, "agent_phone_number": "08064276261",
				"duration": 40, "start_datetime": "2026-11-03T05:30:00Z", "end_datetime": "2026-11-03T05:30:40Z",
				"interaction_transcript": [{"role": "user", "en_text": "Connect me to Kalpana."}],
				"output_agent_variables": variables,
			}
		)

	def _attempt(self, name):
		return frappe.get_doc(ATTEMPT, name)

	# --- named executive ----------------------------------------------------

	def test_named_executive_who_is_free_gets_the_call(self):
		for spoken in ("Kalpana", "kalpa", "KALPANA MUTHU", "Kalpana madam"):
			with self.subTest(spoken=spoken):
				frappe.db.savepoint("named")
				result = self._transfer(executive=spoken)
				self.assertEqual(
					(result["open"], result["target"], result["executive"], result["routed_by"], result["decision"]),
					(True, "+917000001292", "Kalpana", "requested", "TRANSFER"),
				)
				self.assertEqual(result["then"], [])
				row = self._attempt(result["attempt"])
				self.assertEqual((row.status, row.executive, row.user, row.lead), ("Routed", "Kalpana", EXECUTIVES[1][2], self.lead_a))
				self.assertTrue(frappe.local.flags.commit, "a GET must commit the Routed row")
				frappe.db.rollback(save_point="named")

	def test_named_executive_who_is_busy_is_refused_with_the_others_available(self):
		self._make_busy("Kalpana")
		result = self._transfer(executive="Kalpana")
		self.assertEqual((result["open"], result["reason"], result["decision"]), (False, "executive_busy", "CALLBACK"))
		self.assertEqual(result["available"], ["Vinod", "Sravya"])
		row = self._attempt(result["attempt"])
		self.assertEqual((row.status, row.refused_reason, row.executive), ("Refused", "executive_busy", None))
		self.assertIn("Kalpana is busy since", row.decision_log)

	def test_unknown_name_is_not_found_with_everyone_available(self):
		result = self._transfer(executive="Ramesh")
		self.assertEqual((result["open"], result["reason"]), (False, "executive_not_found"))
		self.assertEqual(result["available"], ["Vinod", "Kalpana", "Sravya"])

	def test_named_executive_on_break_is_busy(self):
		self._on_break("Kalpana")
		result = self._transfer(executive="Kalpana")
		self.assertEqual(result["reason"], "executive_busy")
		self.assertIn("Kalpana is on break", self._attempt(result["attempt"]).decision_log)

	def test_disabled_executive_is_not_found(self):
		frappe.db.set_value(va.EXECUTIVE_DOCTYPE, self._executive_row("Kalpana"), "enabled", 0)
		self.assertEqual(self._transfer(executive="Kalpana")["reason"], "executive_not_found")

	def test_unknown_caller_is_refused_whoever_they_ask_for(self):
		for executive in ("Kalpana", None):
			result = self._transfer(UNKNOWN, executive=executive)
			self.assertEqual((result["open"], result["reason"]), (False, "unknown_caller"))
		self.assertFalse(frappe.db.exists(ATTEMPT, {"status": "Routed"}))

	def test_blocked_caller_gets_only_the_gate_and_nothing_is_written(self):
		result = self._transfer(BLOCKED, executive="Kalpana")
		self.assertEqual(set(result), {"allowed", "reason", "message"})
		self.assertFalse(frappe.db.exists(ATTEMPT, {"caller_phone": BLOCKED}))

	def test_outside_hours_keeps_hours_text_and_is_logged(self):
		result = self._transfer(executive="Kalpana", when=datetime(2026, 11, 8, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
		self.assertEqual((result["open"], result["reason"], result["hours_text"]), (False, "outside_hours", "10 AM to 8 PM, Monday to Saturday"))
		self.assertEqual(self._attempt(result["attempt"]).refused_reason, "outside_hours")

	# --- round robin ----------------------------------------------------------

	def test_three_calls_in_a_row_rotate_through_the_executives(self):
		got = [self._transfer(phone)["executive"] for phone in (CALLER_A, CALLER_B, CALLER_OWNED)]
		self.assertEqual(sorted(got), ["Kalpana", "Sravya", "Vinod"])
		self.assertEqual(got, ["Vinod", "Kalpana", "Sravya"], "table order, starting after nobody")
		self.assertTrue(all(self._attempt(n).routed_by == "round_robin" for n in frappe.get_all(ATTEMPT, pluck="name")))
		self.assertEqual(self._transfer(CALLER_A)["reason"], "all_busy")

	def test_rotation_continues_after_the_executives_are_free_again(self):
		first = self._transfer(interaction_id="rr-1")
		self._end("rr-1", transferred=False)
		second = self._transfer(interaction_id="rr-2")
		self.assertEqual((first["executive"], second["executive"]), ("Vinod", "Kalpana"))

	def test_refusals_do_not_move_the_pointer(self):
		self.assertEqual(self._transfer(interaction_id="p-1")["executive"], "Vinod")
		self._end("p-1", transferred=False)
		self._transfer(executive="Nobody")
		self._transfer(UNKNOWN)
		self.assertEqual(self._transfer()["executive"], "Kalpana")

	def test_declining_a_busy_executive_then_accepting_anyone_skips_them(self):
		self._make_busy("Vinod")  # the pointer is now on Vinod
		self._make_busy("Kalpana")
		self.assertEqual(self._transfer(executive="Kalpana", interaction_id="decline")["reason"], "executive_busy")
		retry = self._transfer(interaction_id="decline")
		self.assertEqual((retry["open"], retry["executive"]), (True, "Sravya"))

	def test_one_free_executive_two_callers(self):
		self._on_break("Vinod")
		self._on_break("Sravya")
		first, second = self._transfer(CALLER_A), self._transfer(CALLER_B)
		self.assertEqual((first["open"], first["executive"]), (True, "Kalpana"))
		self.assertEqual((second["open"], second["reason"], second["available"]), (False, "all_busy", []))

	def test_routing_locks_the_executive_rows(self):
		with patch.object(va, "_executive_rows", wraps=va._executive_rows) as rows:
			self._transfer()
		rows.assert_called_once_with(lock=True)
		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
			va._executive_rows(lock=True)
		self.assertIn("for update", sql.call_args.args[0])

	def test_no_executives_is_all_busy(self):
		for name, *_ in EXECUTIVES:
			frappe.db.set_value(va.EXECUTIVE_DOCTYPE, self._executive_row(name), "enabled", 0)
		result = self._transfer()
		self.assertEqual((result["reason"], result["available"]), ("all_busy", []))

	# --- sticky ---------------------------------------------------------------

	def test_sticky_routes_to_the_executive_who_took_the_last_transfer(self):
		self._set(sticky_agent=1)
		first = self._transfer(executive="Sravya", interaction_id="s-1")
		self._end("s-1", transferred=True)
		frappe.db.set_value(ATTEMPT, first["attempt"], "routed_at", add_to_date(now_datetime(), minutes=-20))
		again = self._transfer(interaction_id="s-2")
		self.assertEqual((again["executive"], again["routed_by"]), ("Sravya", "sticky"))

	def test_sticky_executive_busy_falls_through_to_round_robin(self):
		self._set(sticky_agent=1)
		self._transfer(executive="Vinod", interaction_id="s-3")
		self._end("s-3", transferred=True)  # Connected - Vinod stays busy until the timeout
		again = self._transfer(interaction_id="s-4")
		self.assertTrue(again["open"])
		self.assertEqual((again["executive"], again["routed_by"]), ("Kalpana", "round_robin"))
		self.assertIn("Vinod is busy since", self._attempt(again["attempt"]).decision_log)

	def test_sticky_with_no_history_uses_the_lead_owner(self):
		self._set(sticky_agent=1)
		result = self._transfer(CALLER_OWNED)
		self.assertEqual((result["executive"], result["routed_by"]), ("Kalpana", "sticky"))
		self._on_break("Kalpana")
		self.assertEqual(self._transfer(CALLER_OWNED)["routed_by"], "round_robin")

	def test_sticky_off_ignores_history(self):
		self._transfer(executive="Sravya", interaction_id="s-5")
		self._end("s-5", transferred=False)
		self.assertEqual(self._transfer()["routed_by"], "round_robin")

	# --- busy ledger and call end --------------------------------------------

	def test_no_call_end_frees_the_executive_after_the_timeout(self):
		self._set(busy_timeout_minutes=15)
		busy = self._make_busy("Kalpana")
		self.assertEqual(self._transfer(executive="Kalpana")["reason"], "executive_busy")
		frappe.db.set_value(ATTEMPT, busy["attempt"], "routed_at", add_to_date(now_datetime(), minutes=-16))
		self.assertEqual(self._transfer(executive="Kalpana")["executive"], "Kalpana")
		row = self._attempt(busy["attempt"])
		self.assertEqual(row.status, "Expired")
		self.assertEqual(row.ended_at, add_to_date(row.routed_at, minutes=15))

	def test_transfer_not_connected_frees_the_executive_at_once(self):
		result = self._transfer(executive="Kalpana", interaction_id="nc-1")
		log = self._end("nc-1", transferred=False)
		self.assertEqual(self._attempt(result["attempt"]).status, "Not connected")
		self.assertFalse(log.receiver)
		self.assertEqual(self._transfer(executive="Kalpana")["executive"], "Kalpana")

	def test_missing_transferred_flag_is_not_connected(self):
		result = self._transfer(executive="Kalpana", interaction_id="nc-2")
		self._end("nc-2")
		self.assertEqual(self._attempt(result["attempt"]).status, "Not connected")

	def test_transferred_call_sets_connected_and_the_receiver(self):
		result = self._transfer(executive="Kalpana", interaction_id="c-1")
		log = self._end("c-1", transferred=True)
		self.assertEqual((log.status, log.custom_status_reason, log.receiver), ("Completed", "transferred", EXECUTIVES[1][2]))
		self.assertEqual(self._attempt(result["attempt"]).status, "Connected")
		self.assertEqual(self._transfer(executive="Kalpana")["reason"], "executive_busy", "busy until the timeout")
		frappe.db.set_value(ATTEMPT, result["attempt"], "routed_at", add_to_date(now_datetime(), minutes=-16))
		va.expire_transfer_attempts()
		self.assertEqual(self._attempt(result["attempt"]).status, "Ended")

	def test_late_or_repeated_webhook_changes_nothing(self):
		result = self._transfer(executive="Kalpana", interaction_id="r-1")
		self._end("r-1", transferred=False)
		closed = self._attempt(result["attempt"])
		for transferred in (False, True):
			self._end("r-1", transferred=transferred)
		again = self._attempt(result["attempt"])
		self.assertEqual((again.status, again.ended_at, again.decision_log), (closed.status, closed.ended_at, closed.decision_log))
		self.assertEqual(frappe.db.count("CRM Call Log", {"id": "r-1"}), 1)

	def test_webhook_matches_by_interaction_id_only(self):
		mine = self._transfer(executive="Kalpana", interaction_id="m-1")
		other = self._transfer(CALLER_B, executive="Vinod", interaction_id="m-2")
		self._end("m-1", transferred=False)
		self.assertEqual((self._attempt(mine["attempt"]).status, self._attempt(other["attempt"]).status), ("Not connected", "Routed"))
		self._end("no-attempt-call", transferred=True)  # no attempt: nothing else happens
		self.assertEqual(self._attempt(other["attempt"]).status, "Routed")

	def test_interaction_id_from_caller_gate_check_closes_the_attempt(self):
		from core_customizations.core_customizations.caller_gate import check

		iid = "20261104/44095154-03:06:25-a3c8ce7a"
		echoed = check(phone=CALLER_A, key=KEY, interaction_id=iid)["interaction_id"]
		result = self._transfer(executive="Kalpana", interaction_id=echoed)
		self._end(iid, transferred=False)
		self.assertEqual(self._attempt(result["attempt"]).status, "Not connected")

	def test_routing_the_same_call_again_frees_the_first_executive(self):
		first = self._transfer(executive="Kalpana", interaction_id="again-1")
		second = self._transfer(executive="Vinod", interaction_id="again-1")
		self.assertEqual((self._attempt(first["attempt"]).status, second["executive"]), ("Not connected", "Vinod"))

	def test_busy_check_fails_open(self):
		self._make_busy("Kalpana")
		real_sql = frappe.db.sql

		def broken(query, *args, **kwargs):
			if "min(routed_at)" in str(query):
				raise frappe.db.InternalError("ledger unreadable")
			return real_sql(query, *args, **kwargs)

		with patch.object(frappe.db, "sql", side_effect=broken), patch.object(frappe, "log_error") as log_error:
			result = self._transfer(executive="Kalpana")
		self.assertEqual((result["open"], result["executive"]), (True, "Kalpana"))
		log_error.assert_called_once()

	def test_internal_error_returns_reason_error_and_writes_no_route(self):
		with patch.object(va, "_round_robin", side_effect=RuntimeError("boom")), patch.object(frappe, "log_error") as log_error:
			result = self._transfer()
		self.assertEqual((result["allowed"], result["open"], result["reason"], result["decision"]), (True, False, "error", "CALLBACK"))
		self.assertEqual(result["hours_text"], "10 AM to 8 PM, Monday to Saturday")
		self.assertFalse(frappe.db.exists(ATTEMPT, {"status": "Routed"}))
		log_error.assert_called_once()

	def test_wrong_key_still_raises(self):
		with self.assertRaises(frappe.PermissionError):
			va.transfer_target(phone=CALLER_A, key="wrong")

	def test_busy_list_and_clear_button(self):
		self._make_busy("Kalpana")
		self._on_break("Sravya")
		busy = {e["executive"]: e for e in va.busy_executives()}
		self.assertEqual((busy["Kalpana"]["busy"], busy["Kalpana"]["status"], busy["Kalpana"]["caller_phone"]), (True, "Routed", CALLER_B))
		self.assertEqual((busy["Sravya"]["busy"], busy["Sravya"]["on_break"]), (True, 1))
		self.assertFalse(busy["Vinod"]["busy"])
		self.assertEqual(va.clear_busy_executives(), {"cleared": 1})
		after = {e["executive"]: e for e in va.busy_executives()}
		self.assertEqual((after["Kalpana"]["busy"], after["Sravya"]["on_break"]), (False, 1), "On Break is left alone")
		frappe.set_user(EXECUTIVES[0][2])  # a Sales User
		with self.assertRaises(frappe.PermissionError):
			va.clear_busy_executives()
