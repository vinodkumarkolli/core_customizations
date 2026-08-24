# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

"""
Shared ERPNext master data fixture helpers for CI test environments.

WHY THIS EXISTS:
In a production ERPNext instance, master data like Customer Groups, Territories,
Units of Measure, and Price Lists are created during the setup wizard. However,
the CI pipeline creates a blank site via `bench new-site` and installs ERPNext
without running the wizard. This means all tests that create Customers, Suppliers,
or Items against standard ERPNext master data will fail with LinkValidationError.

This module provides a single `ensure_test_fixtures()` function that any test's
`setUpClass` can call to idempotently create the minimum required master data
before attempting to insert any business documents.
"""

import frappe


def ensure_test_fixtures():
    """
    Idempotently create the minimum ERPNext master data required for CI tests.

    This function is safe to call multiple times — it checks for existence before
    inserting. It creates:
    - UOM: Nos
    - Item Group: Products
    - Customer Group: Commercial
    - Territory: All Territories and India
    - Price List: Standard Selling
    - Supplier Group: Local, Services
    - Warehouse: Stores (for the default company)
    """
    # --- Units of Measure ---
    for uom in ["Nos", "Kg", "Litre"]:
        if not frappe.db.exists("UOM", uom):
            frappe.get_doc({"doctype": "UOM", "uom_name": uom}).insert(ignore_permissions=True)

    # --- Item Groups ---
    # The root "All Item Groups" must exist before creating children
    if not frappe.db.exists("Item Group", "All Item Groups"):
        frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": "All Item Groups",
            "is_group": 1
        }).insert(ignore_permissions=True)

    if not frappe.db.exists("Item Group", "Products"):
        frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": "Products",
            "parent_item_group": "All Item Groups"
        }).insert(ignore_permissions=True)

    # --- Customer Groups ---
    if not frappe.db.exists("Customer Group", "All Customer Groups"):
        frappe.get_doc({
            "doctype": "Customer Group",
            "customer_group_name": "All Customer Groups",
            "is_group": 1
        }).insert(ignore_permissions=True)

    if not frappe.db.exists("Customer Group", "Commercial"):
        frappe.get_doc({
            "doctype": "Customer Group",
            "customer_group_name": "Commercial",
            "parent_customer_group": "All Customer Groups"
        }).insert(ignore_permissions=True)

    # --- Territories ---
    if not frappe.db.exists("Territory", "All Territories"):
        frappe.get_doc({
            "doctype": "Territory",
            "territory_name": "All Territories",
            "is_group": 1
        }).insert(ignore_permissions=True)

    if not frappe.db.exists("Territory", "India"):
        frappe.get_doc({
            "doctype": "Territory",
            "territory_name": "India",
            "parent_territory": "All Territories"
        }).insert(ignore_permissions=True)

    # --- Price Lists ---
    if not frappe.db.exists("Price List", "Standard Selling"):
        frappe.get_doc({
            "doctype": "Price List",
            "price_list_name": "Standard Selling",
            "selling": 1,
            "currency": "INR"
        }).insert(ignore_permissions=True)

    if not frappe.db.exists("Price List", "Standard Buying"):
        frappe.get_doc({
            "doctype": "Price List",
            "price_list_name": "Standard Buying",
            "buying": 1,
            "currency": "INR"
        }).insert(ignore_permissions=True)

    # --- Supplier Groups ---
    if not frappe.db.exists("Supplier Group", "All Supplier Groups"):
        frappe.get_doc({
            "doctype": "Supplier Group",
            "supplier_group_name": "All Supplier Groups",
            "is_group": 1
        }).insert(ignore_permissions=True)

    for sg in ["Local", "Services"]:
        if not frappe.db.exists("Supplier Group", sg):
            frappe.get_doc({
                "doctype": "Supplier Group",
                "supplier_group_name": sg,
                "parent_supplier_group": "All Supplier Groups"
            }).insert(ignore_permissions=True)

    # --- Company & Default Accounts ---
    if not frappe.db.exists("Role", "Employee Self Service"):
        frappe.get_doc({
            "doctype": "Role",
            "role_name": "Employee Self Service"
        }).insert(ignore_permissions=True)
        
    if not frappe.db.exists("Company", "Test Company"):
        frappe.get_doc({
            "doctype": "Company",
            "company_name": "Test Company",
            "default_currency": "INR",
            "country": "India",
            "abbr": "TC"
        }).insert(ignore_permissions=True)

    # --- Fiscal Year Extension ---
    # ERPNext creates standard test fiscal years which might expire based on current date.
    # Extend all fiscal years to 2030 so that nowdate() always falls within them.
    frappe.db.sql("UPDATE `tabFiscal Year` SET year_end_date='2030-03-31'")
    frappe.cache().delete_key("fiscal_years")
    frappe.clear_cache()
    
    # Sometimes creating a company creates the default warehouse, sometimes it doesn't.
    if not frappe.db.exists("Warehouse", "Stores - TC"):
        frappe.get_doc({
            "doctype": "Warehouse",
            "warehouse_name": "Stores",
            "company": "Test Company",
            "is_group": 0
        }).insert(ignore_permissions=True)

    # --- Default Address Template ---
    # Required for get_address_display() which is called on ExtendedAddress save hooks
    if not frappe.db.exists("Address Template", {"is_default": 1}):
        frappe.get_doc({
            "doctype": "Address Template",
            "country": "India",
            "template": "{{ address_line1 }}<br>{{ city }}<br>{{ state }} - {{ pincode }}<br>{{ country }}",
            "is_default": 1
        }).insert(ignore_permissions=True)

    frappe.db.commit()
