import frappe
# Method: get_mobile_keys
@frappe.whitelist(allow_guest=True)
def login_and_get_keys(usr, pwd):
    try:
        # 1. Manually authenticate the user
        login_manager = frappe.auth.LoginManager()
        login_manager.authenticate(user=usr, pwd=pwd)
        login_manager.post_login()
        
        # 2. At this point, frappe.session.user is set
        user = frappe.session.user
        user_doc = frappe.get_doc("User", user)
        
        # 3. Handle API Key & Secret
        api_secret = None
        try:
            api_secret = user_doc.get_password("api_secret")
        except frappe.ValidationError:
            # Secret not found
            pass

        if not api_secret or not user_doc.api_key:
            if not user_doc.api_key:
                user_doc.api_key = frappe.generate_hash(length=15)
            
            api_secret = frappe.generate_hash(length=15)
            user_doc.api_secret = api_secret
            user_doc.save(ignore_permissions=True)
        
        return {
            "api_key": user_doc.api_key,
            "api_secret": api_secret,
            "full_name": user_doc.full_name
        }
        
    except frappe.AuthenticationError:
        frappe.throw("Invalid login credentials", frappe.AuthenticationError)