# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt
"""
Patch to remove custom file folders.

This patch removes specific custom folders created earlier and moves any files inside
to the 'Home' folder before deletion.
"""

import frappe


def execute():
	folders = ["Employee Images", "Store Images", "Vehicle Images", "Location Images", "Activity Images and Videos"]
	for folder_name in folders:
		if frappe.db.exists("File", {"file_name": folder_name, "is_folder": 1}):
			# Get all files inside the folder and move them to Home or delete them?
			# The user just said "remove those folders". Usually, we should be careful if there are files.
			# But if they are "custom folders" created by a previous patch/hook, they might be empty or 
			# the user wants them gone. I'll delete the folder and its children to be thorough, 
			# or just the folder if it's empty.
			
			folder_doc = frappe.get_doc("File", {"file_name": folder_name, "is_folder": 1})
			
			# Check if there are any files inside
			files_inside = frappe.get_all("File", filters={"folder": folder_doc.name})
			
			if files_inside:
				print(f"Folder {folder_name} is not empty. Moving files to Home before deletion.")
				for file_in in files_inside:
					frappe.db.set_value("File", file_in.name, "folder", "Home")
			
			frappe.delete_doc("File", folder_doc.name, ignore_permissions=True)
			print(f"Removed folder: {folder_name}")
