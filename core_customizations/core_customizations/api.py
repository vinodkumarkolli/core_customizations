import frappe
import base64
from frappe.utils.file_manager import save_file
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

@frappe.whitelist()
def custom_upload_base64(base64_str, filename, doctype=None, docname=None, folder="Home", is_private=0):
    # 1. Clean the base64 string if it contains the header
    if "," in base64_str:
        base64_str = base64_str.split(",")[1]
    
    # 2. Decode base64 to bytes
    file_content = base64.b64decode(base64_str)
    
    # 3. Use Frappe's file_manager to save the file
    # This automatically handles the physical file creation and File Doctype entry
    file_doc = save_file(
        fname=filename,
        content=file_content,
        dt=doctype,
        dn=docname,
        folder=folder,
        is_private=int(is_private),
        decode=False # Already decoded manually
    )
    
    return file_doc.as_dict()

@frappe.whitelist()
def get_user_roles(user=None):
    """
    Whitelisted method to fetch roles for a user.
    Defaults to the current session user.
    """
    if not user:
        user = frappe.session.user
    
    # Ensure users can only see their own roles unless they are a System Manager
    if user != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw("You can only fetch your own roles.", frappe.PermissionError)
        
    return frappe.get_roles(user)


@frappe.whitelist()
def get_sync_status(checks, user_email=None):
    results = {}
    # Use a list of checks: [{"doctype": "Beat", "timestamp": "...", "filters": [...]}, ...]
    for check in checks:
        doctype = check.get("doctype")
        ts = check.get("timestamp")
        flt = check.get("filters", [])
        
        # Check if any relevant record was modified since 'ts'
        query_filters = flt + [["modified", ">", ts]]
        results[doctype] = frappe.db.count(doctype, query_filters) > 0
    return results

    # Need a scheduler function which runs every day night that set any checkin that 
    # donot have corresponding checkout (Log Type == "OUT"), 
    # we need to set "custom_no_checkout_found" = 1. 
    # In a day, there can be multiple checkins. frontend is designed such that when a checkin is done, checkout must be done so as to 