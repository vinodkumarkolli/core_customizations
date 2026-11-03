# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class BlockedContactRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		blocked_contact: DF.Link | None
		decision_notes: DF.SmallText | None
		lead: DF.Link
		lead_name: DF.Data | None
		mobile_no: DF.Data | None
		reason: DF.SmallText
		requested_by: DF.Link | None
		workflow_state: DF.Link | None
	# end: auto-generated types

	def validate(self):
		"""
		Business Purpose: [BR-CRM-003] `lead_name`/`mobile_no` are snapshotted
		from the Lead at escalation time (via `fetch_from`, reinforced here so
		it holds even for a request created without going through the Desk
		form) rather than tracking the Lead live - the Blocked Contact
		eventually created on approval must block the number as it was
		escalated, not whatever the Lead's `mobile_no` happens to be edited to
		later while the request is pending review.
		"""
		if self.is_new():
			lead = frappe.db.get_value("CRM Lead", self.lead, ["lead_name", "mobile_no"], as_dict=True)
			if not lead:
				frappe.throw(_("CRM Lead {0} not found").format(self.lead))
			if not lead.mobile_no:
				frappe.throw(_("{0} has no mobile number to escalate for blocking.").format(self.lead))
			self.lead_name = lead.lead_name
			self.mobile_no = lead.mobile_no

			# @businessRule [BR-CRM-003] One open escalation per Lead at a
			# time - a second click (or a second person) raising the same
			# Lead while the first request is still Pending would otherwise
			# race to create/approve two requests for the same number.
			duplicate = frappe.db.exists(
				"Blocked Contact Request",
				{"lead": self.lead, "workflow_state": ("in", ("Draft", "Pending")), "name": ("!=", self.name)},
			)
			if duplicate:
				frappe.throw(
					_("{0} already has an open blocking escalation: {1}").format(self.lead, duplicate)
				)
