import frappe
from frappe.tests.utils import FrappeTestCase

class TestPurchaseInvoice3PLValidation(FrappeTestCase):
    def setUp(self):
        self.item_3pl = "Test 3PL Item"
        self.item_regular = "Test Regular Item"
        
        if not frappe.db.exists("Item", self.item_3pl):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": self.item_3pl,
                "item_name": self.item_3pl,
                "item_group": "Products",
                "stock_uom": "Nos",
                "is_stock_item": 1,
                "custom_3pl_item": 1,
                "gst_hsn_code": "30049011"
            }).insert()
            
        if not frappe.db.exists("Item", self.item_regular):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": self.item_regular,
                "item_name": self.item_regular,
                "item_group": "Products",
                "stock_uom": "Nos",
                "is_stock_item": 1,
                "custom_3pl_item": 0,
                "gst_hsn_code": "30049011"
            }).insert()

        self.supplier = frappe.db.get_value("Supplier", None, "name") or "Test Supplier"
        if not frappe.db.exists("Supplier", self.supplier):
            frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": self.supplier,
                "supplier_group": "Local"
            }).insert()
            
        self.company = frappe.db.get_value("Company", None, "name")
        self.expense_account = frappe.db.get_value("Account", {"company": self.company, "account_type": "Expense Account"}, "name")
        self.cost_center = frappe.db.get_value("Cost Center", {"company": self.company}, "name")

    def test_01_standalone_pi_with_3pl_item_fails(self):
        pi = frappe.get_doc({
            "doctype": "Purchase Invoice",
            "supplier": self.supplier,
            "company": self.company,
            "items": [{
                "item_code": self.item_3pl,
                "qty": 10,
                "rate": 100,
                "expense_account": self.expense_account,
                "cost_center": self.cost_center
            }]
        })
        
        with self.assertRaises(frappe.ValidationError) as context:
            pi.insert()
            
        self.assertTrue("must be billed against a Purchase Receipt" in str(context.exception))

    def test_02_pi_with_update_stock_for_3pl_item_fails(self):
        pi = frappe.get_doc({
            "doctype": "Purchase Invoice",
            "supplier": self.supplier,
            "company": self.company,
            "update_stock": 1,
            "items": [{
                "item_code": self.item_3pl,
                "qty": 10,
                "rate": 100,
                "expense_account": self.expense_account,
                "cost_center": self.cost_center
            }]
        })
        
        with self.assertRaises(frappe.ValidationError) as context:
            pi.insert()
            
        self.assertTrue("cannot update stock directly from a Purchase Invoice" in str(context.exception))

    def test_03_standalone_pi_with_regular_item_passes(self):
        pi = frappe.get_doc({
            "doctype": "Purchase Invoice",
            "supplier": self.supplier,
            "company": self.company,
            "items": [{
                "item_code": self.item_regular,
                "qty": 10,
                "rate": 100,
                "expense_account": self.expense_account,
                "cost_center": self.cost_center
            }]
        })
        
        pi.insert()
        self.assertTrue(pi.name)
