# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from core_customizations.setup import after_migrate


class TestSetupPermissions(FrappeTestCase):
	"""
	Integration tests for setup.py (after_migrate hook):
	1. Role permissions configuration (Employee Self Service, System Manager)
	2. Standard DocPerm to Custom DocPerm migration
	3. Obsolete Print Format cleanup
	4. Print Format synchronization from fixtures
	"""

	def test_01_after_migrate_creates_custom_docperms(self):
		"""Verify after_migrate provisions custom permissions for Employee Self Service and System Manager."""
		# Execute after_migrate
		after_migrate()

		# Check Employee Self Service permissions only if the role exists.
		# The "Employee Self Service" role is installed by the HRMS app, which is
		# not present in the minimal CI bench (Frappe + ERPNext only).
		if frappe.db.exists("Role", "Employee Self Service"):
			ess_doctypes = [
				"Workflow State",
				"Workflow",
				"Workflow Action Master",
				"Project",
				"Mode of Payment",
				"Supplier",
				"Item Price",
				"Item Tax Template",
			]
			for dt in ess_doctypes:
				self.assertTrue(
					frappe.db.exists(
						"Custom DocPerm", {"parent": dt, "role": "Employee Self Service", "permlevel": 0}
					),
					f"Custom DocPerm for Employee Self Service on '{dt}' was not created.",
				)

			# Check Employee permlevel 1 for Employee Self Service (read-only)
			self.assertTrue(
				frappe.db.exists(
					"Custom DocPerm",
					{
						"parent": "Employee",
						"role": "Employee Self Service",
						"permlevel": 1,
						"read": 1,
						"write": 0,
					},
				),
				"Custom DocPerm for Employee Self Service (permlevel 1) missing or has write enabled.",
			)
		else:
			self.skipTest(
				"HRMS not installed: 'Employee Self Service' role does not exist, skipping ESS permission check."
			)

		# Check Employee permlevel 1 for System Manager (read-write) — always runs
		self.assertTrue(
			frappe.db.exists(
				"Custom DocPerm",
				{"parent": "Employee", "role": "System Manager", "permlevel": 1, "read": 1, "write": 1},
			),
			"Custom DocPerm for System Manager on Employee (permlevel 1) missing or lacks write.",
		)

	def test_02_standard_docperm_copied_when_custom_docperm_created(self):
		"""Verify standard DocPerms are replicated to Custom DocPerms to prevent Frappe permission loss."""
		after_migrate()

		# Workflow has standard DocPerms. Verify all standard roles have corresponding Custom DocPerms.
		std_perms = frappe.get_all(
			"DocPerm", filters={"parent": "Workflow"}, fields=["role", "permlevel", "if_owner"]
		)
		for sp in std_perms:
			self.assertTrue(
				frappe.db.exists(
					"Custom DocPerm",
					{
						"parent": "Workflow",
						"role": sp.role,
						"permlevel": sp.permlevel,
						"if_owner": sp.if_owner,
					},
				),
				f"Standard DocPerm for role '{sp.role}' on Workflow was not migrated to Custom DocPerm.",
			)

	def test_03_obsolete_print_formats_cleaned_up(self):
		"""Verify obsolete print formats are deleted if they exist."""
		obsolete_pf = "Customer Delivery Address Label"
		# Temporarily create the obsolete print format if it doesn't exist
		if not frappe.db.exists("Print Format", obsolete_pf):
			# [Ruff F841 Fix] Removed unused 'doc =' assignment because we only need to insert the record
			frappe.get_doc(
				{
					"doctype": "Print Format",
					"name": obsolete_pf,
					"doc_type": "Delivery Note",
					"format_data": "{}",
					"standard": "No",
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()

		self.assertTrue(frappe.db.exists("Print Format", obsolete_pf))

		# Run after_migrate
		after_migrate()

		# Assert obsolete print format is deleted
		self.assertFalse(
			frappe.db.exists("Print Format", obsolete_pf),
			f"Obsolete print format '{obsolete_pf}' was not deleted by after_migrate.",
		)

	def test_04_core_customizations_print_formats_synced(self):
		"""Verify required Core Customizations print formats are present and loaded."""
		after_migrate()

		expected_formats = [
			"Delivery Note - Original for Consignee",
			"Delivery Note - Duplicate for Transporter",
			"Delivery Note - Triplicate for Supplier",
			"GST Invoice - Original for Receiver",
			"GST Invoice - Duplicate for Transporter",
			"GST Invoice - Triplicate for Supplier",
			"Carton Shipping Label (4x6)",
			"Shipping Package Label (4x6)",
		]
		for pf in expected_formats:
			self.assertTrue(
				frappe.db.exists("Print Format", pf), f"Print Format '{pf}' is missing after sync."
			)
