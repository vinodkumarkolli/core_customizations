# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class BlockedContact(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		added_by: DF.Link | None
		enabled: DF.Check
		mobile_no: DF.Data
		reason: DF.SmallText | None
	# end: auto-generated types

	def before_insert(self):
		"""
		Business Purpose: [BR-CRM-002] `autoname: field:mobile_no` reads
		`mobile_no` to build `name` during `insert()`'s `set_new_name()`
		step, which runs right after `before_insert` but before `validate`
		- so normalising only in `validate` (as it also does below, for
		edits) would leave a row entered as "+91 98404 56658" permanently
		named that raw string instead of "9840456658", even though its
		`mobile_no` field gets cleaned up afterwards. Normalising here
		first means `name` and `mobile_no` always agree.
		"""
		self._normalise_mobile_no()

	def validate(self):
		"""
		Business Purpose: [BR-CRM-002] Whatever format a number is typed in
		here (+91, 91, 0-prefixed, with spaces, ...), it is stored the same
		way `caller_gate.is_blocked_number` looks it up - the last 10 digits
		only - so a row entered as "+91 98404 56658" and a lookup for
		"9840456658" are recognised as the same number. Covers edits too,
		even though only `before_insert` affects `name` (`allow_rename` is
		off, so an edited `mobile_no` never renames the doc).
		"""
		self._normalise_mobile_no()

	def _normalise_mobile_no(self):
		from core_customizations.core_customizations.caller_gate import last_10_digits

		normalised = last_10_digits(self.mobile_no)
		if not normalised:
			frappe.throw(_("{0} does not look like a 10-digit mobile number.").format(self.mobile_no))
		self.mobile_no = normalised
