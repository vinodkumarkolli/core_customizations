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
"""

import frappe
from frappe.utils import nowdate

from core_customizations.core_customizations.caller_gate import get_automation_user
from core_customizations.core_customizations.voice_agent import CALLBACK_TASK_TITLE_PREFIX, OPEN_TASK_STATUSES

REPORT_ROUTE = ["List", "CRM Task", "Report"]


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


def _card(filters):
	count = len(frappe.get_list("CRM Task", filters=filters, pluck="name", limit_page_length=0))
	return {"value": count, "fieldtype": "Int", "route": REPORT_ROUTE, "route_options": filters}


@frappe.whitelist()
def callbacks_awaiting(filters=None):
	"""Number Card "Callbacks Awaiting": open voice-agent callback Tasks."""
	return _card(callback_filters())


@frappe.whitelist()
def overdue_callbacks(filters=None):
	"""Number Card "Overdue Callbacks": open voice-agent callback Tasks from before today."""
	return _card(callback_filters(overdue=True))
