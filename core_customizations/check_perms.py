import frappe
from frappe.model.document import Document
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

def execute():
    doctype = "Stock Settings"
    # Clear cache to be sure
    frappe.clear_cache(doctype=doctype)
    
    meta = frappe.get_meta(doctype)
    
    print(f"Meta permissions count: {len(meta.permissions)}")
    for p in meta.permissions:
        print(f"Permission Role: {p.role}, Read: {p.read}")
    
    # Simulate set_custom_permissions logic
    custom_perms = frappe.get_all(
        "Custom DocPerm",
        fields="*",
        filters=dict(parent=doctype),
        update=dict(doctype="Custom DocPerm"),
    )
    print(f"Custom DocPerm count: {len(custom_perms)}")
    
    if custom_perms:
        simulated_perms = [Document(d) for d in custom_perms]
        print(f"Simulated permissions count: {len(simulated_perms)}")
        
    # Check flags
    print(f"in_patch: {frappe.flags.in_patch}")
    print(f"in_install: {frappe.flags.in_install}")
    
    # Check istable
    print(f"istable: {meta.istable}")

    # Find a user with the role
    real_user = frappe.db.sql("""
        select parent from `tabHas Role` 
        where role='Field Sales User' and parenttype='User' 
        limit 1
    """)
    
    if real_user:
        user = real_user[0][0]
        print(f"Testing with user: {user}")
        
        print("Has Role entry:", frappe.db.get_all("Has Role", filters={"parent": user, "role": "Field Sales User"}, fields=["*"]))
        
        frappe.clear_cache(user=user)
        
        has_perm = frappe.has_permission(doctype, user=user)
        print(f"Has Permission: {has_perm}")
        
        # Debug has_permission
        roles = frappe.get_roles(user)
        print(f"User Roles: {roles}")
        
        # Debug get_role_permissions logic
        meta = frappe.get_meta(doctype)
        
        applicable_permissions = []
        for p in meta.permissions:
            if p.role in roles and p.permlevel == 0:
                applicable_permissions.append(p)
                
        print(f"Applicable permissions: {applicable_permissions}")
        
        perms = {}
        for ptype in ['read', 'write', 'create']:
            pvalue = any(p.get(ptype, 0) for p in applicable_permissions)
            perms[ptype] = int(pvalue)
            
        print(f"Calculated perms: {perms}")
        
        # Check hooks
        print("Hooks has_permission:", frappe.get_hooks("has_permission"))
        
        # Check User Permissions
        print("User Permissions Details:", frappe.get_all("User Permission", filters={"user": user}, fields=["allow", "for_value", "applicable_for"]))
        
        meta = frappe.get_meta(doctype)
        print("Link Fields:", [(df.fieldname, df.options) for df in meta.get_link_fields()])
        
        print("default_warehouse:", frappe.db.get_single_value("Stock Settings", "default_warehouse"))
        print("sample_retention_warehouse:", frappe.db.get_single_value("Stock Settings", "sample_retention_warehouse"))
        
        # Try to set ignore_user_permissions via Property Setter
        print("Setting Property Setter...")
        
        for fieldname in ["default_warehouse", "sample_retention_warehouse"]:
            make_property_setter("Stock Settings", fieldname, "ignore_user_permissions", 1, "Check")
            
        # Clear cache
        frappe.clear_cache(doctype="Stock Settings")
        
        # Check has_user_permission again
        doc = frappe.get_doc(doctype, doctype)
        print("Has User Permission after fix:", frappe.permissions.has_user_permission(doc, user=user))
        
        has_perm = frappe.has_permission(doctype, user=user)
        print(f"Has Permission after fix: {has_perm}")

    else:
        print("No real user found with role Field Sales User")

if __name__ == "__main__":
    execute()
