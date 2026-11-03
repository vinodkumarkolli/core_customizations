# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
[BR-CRM-009] The Callbacks workspace's two Number Cards: how many voice-agent
callback requests are waiting, and how many of those are overdue. Clicking a
card opens the CRM Task Report View with the same filters, so the number and
the list behind it can never disagree.

A voice-agent callback is a CRM Task that `voice_agent.save_request` created:
its title starts with "Callback:" and its owner is the Caller Gate Automation
User the agent runs as (read from Sarvam Voice Agent Settings, never
hardcoded; when that is blank, the title alone decides). Tasks staff create
by hand are not counted. Waiting = status Backlog, Todo or In Progress;
overdue = waiting and its start date is before today.

Both methods are Custom Number Card methods: they take the card's `filters`
argument (unused) and count only the Tasks the signed-in user may read.

[BR-CRM-010] The same workspace also counts this month's inbound voice-agent
calls (CRM Call Logs of type Incoming, medium Sarvam, written by
`voice_agent.record_inbound_call`) by how they ended: "Live Agent Answered"
(Completed, transferred to a person), "Resolved by Sarvam" (Completed, not
transferred) and "Blocked Calls" (status Blocked - blocked list or
non-Indian number). Each opens the CRM Call Log Report View with its filters.
"""

import frappe
from frappe.utils import nowdate

from core_customizations.core_customizations.caller_gate import get_automation_user
from core_customizations.core_customizations.voice_agent import (
	BLOCKED_CALL_STATUS,
	CALLBACK_TASK_TITLE_PREFIX,
	OPEN_TASK_STATUSES,
	REASON_TRANSFERRED,
)

REPORT_ROUTE = ["List", "CRM Task", "Report"]
CALL_REPORT_ROUTE = ["List", "CRM Call Log", "Report"]
CALL_PERIOD = ["Timespan", "this month"]


def callback_filters(overdue=False):
	"""The filters both the count and the Report View use, as route options."""
	filters = {
		"title": ["like", f"{CALLBACK_TASK_TITLE_PREFIX}%"],
		"status": ["in", list(OPEN_TASK_STATUSES)],
	}
	automation_user = get_automation_user()
	if automation_user:
		filters["owner"] = automation_user
	if overdue:
		filters["start_date"] = ["<", nowdate()]
	return filters


def _card(filters, doctype="CRM Task", route=REPORT_ROUTE):
	count = len(frappe.get_list(doctype, filters=filters, pluck="name", limit_page_length=0))
	return {"value": count, "fieldtype": "Int", "route": route, "route_options": filters}


@frappe.whitelist()
def callbacks_awaiting(filters=None):
	"""Number Card "Callbacks Awaiting": open voice-agent callback Tasks."""
	return _card(callback_filters())


@frappe.whitelist()
def overdue_callbacks(filters=None):
	"""Number Card "Overdue Callbacks": open voice-agent callback Tasks from before today."""
	return _card(callback_filters(overdue=True))


def call_filters(outcome):
	"""
	[BR-CRM-010] This month's inbound voice-agent Call Logs that ended as
	`outcome` - "live_agent", "sarvam" or "blocked" - as route options.
	"""
	filters = {"type": "Incoming", "telephony_medium": "Sarvam", "creation": CALL_PERIOD}
	if outcome == "live_agent":
		filters.update(status="Completed", custom_status_reason=REASON_TRANSFERRED)
	elif outcome == "sarvam":
		filters.update(status="Completed", custom_status_reason=["is", "not set"])
	elif outcome == "blocked":
		filters["status"] = BLOCKED_CALL_STATUS
	else:
		frappe.throw(f"Unknown call outcome: {outcome}")
	return filters


def _call_card(outcome):
	return _card(call_filters(outcome), doctype="CRM Call Log", route=CALL_REPORT_ROUTE)


@frappe.whitelist()
def live_agent_answered_calls(filters=None):
	"""Number Card "Live Agent Answered": this month's calls the agent transferred to a person."""
	return _call_card("live_agent")


@frappe.whitelist()
def resolved_by_sarvam_calls(filters=None):
	"""Number Card "Resolved by Sarvam": this month's completed calls the agent handled itself."""
	return _call_card("sarvam")


@frappe.whitelist()
def blocked_calls(filters=None):
	"""Number Card "Blocked Calls": this month's calls from a blocked or non-Indian number."""
	return _call_card("blocked")
