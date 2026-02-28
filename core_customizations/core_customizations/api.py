import frappe
import base64
from frappe.utils.file_manager import save_file
from frappe.utils import today, getdate
import re

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

@frappe.whitelist()
def get_items_configured(filters=None):
    try:
        # Handle stringified filters from frontend
        if isinstance(filters, str):
            filters = frappe.parse_json(filters)
            
        if not filters:
            filters = [["disabled", "=", 0], ["is_sales_item", "=", 1], ["has_variants", "=", 0]]
        # 1. Fetch main item data
        items = frappe.get_list("Item", 
            fields=["name", "item_code", "item_name", "item_group", "stock_uom", "disabled", "is_sales_item", "has_variants", "image", "modified"],
            filters=filters,
            limit_page_length=5000
        )
        
        if not items:
            return []
        # 2. Get today's date as a date object
        current_date = getdate(today())
        # 3. Bulk fetch ALL taxes for these items at once
        item_names = [i.name for i in items]
        all_taxes = frappe.get_all("Item Tax",
            fields=["parent", "item_tax_template", "valid_from"],
            filters={ "parent": ["in", item_names], "docstatus": 0 },
            order_by="valid_from desc"
        )
        # Map taxes to parents for quick lookup
        tax_map = {}
        for t in all_taxes:
            if t.parent not in tax_map:
                tax_map[t.parent] = []
            tax_map[t.parent].append(t)
        # 4. Map back to items
        for item in items:
            gst_rate = 18.0 # Default
            item_taxes = tax_map.get(item.name, [])
            
            # Find the most recent applicable template
            active_tax = None
            for t in item_taxes:
                # Ensure we compare date objects
                tax_date = getdate(t.valid_from) if t.valid_from else None
                if not tax_date or tax_date <= current_date:
                    active_tax = t
                    break
            
            if active_tax and active_tax.item_tax_template:
                match = re.search(r"(\d+)", active_tax.item_tax_template)
                if match:
                    gst_rate = float(match.group(1))
            
            item["item_gst_rate"] = gst_rate
        return items
        
    except Exception as e:
        frappe.log_error(title="Owlly get_items_configured crash", message=frappe.get_traceback())
        raise e
@frappe.whitelist()
def get_timesheets_configured(filters=None):
    try:
        # Handle stringified filters from frontend
        if isinstance(filters, str):
            filters = frappe.parse_json(filters)
            
        # 1. Fetch main Timesheet data
        timesheets = frappe.get_list("Timesheet", 
            fields=["name", "employee", "parent_project", "start_date", "status", "total_hours", "modified"],
            filters=filters,
            limit_page_length=5000
        )
        
        if not timesheets:
            return []
        # 2. Bulk fetch ALL child Time Logs for these timesheets
        timesheet_names = [ts.name for ts in timesheets]
        all_logs = frappe.get_all("Timesheet Detail", # Note: Child table is 'Timesheet Detail' in standard Frappe
            fields=["parent", "activity_type", "from_time", "to_time", "project", "task", "description", "hours", "name"],
            filters={ "parent": ["in", timesheet_names], "docstatus": ["<", 2] },
            order_by="from_time desc"
        )
        # Map logs to parents for quick lookup
        log_map = {}
        for log in all_logs:
            if log.parent not in log_map:
                log_map[log.parent] = []
            log_map[log.parent].append(log)
        # 3. Map back to timesheets
        for ts in timesheets:
            ts["time_logs"] = log_map.get(ts.name, [])
            
        return timesheets
        
    except Exception as e:
        frappe.log_error(title="Owlly get_timesheets_configured crash", message=frappe.get_traceback())
        raise e
@frappe.whitelist()
def get_pos_profiles_configured(user=None, filters=None):
    if not user:
        user = frappe.session.user
    
    # 1. Get all enabled POS Profiles
    profiles = frappe.get_list("POS Profile",
        fields=["name", "company", "disabled", "warehouse", "customer", "currency", 
                "income_account", "expense_account", "write_off_account", "write_off_cost_center", 
                "cost_center", "selling_price_list", "modified"],
        filters={"disabled": 0}
    )
    
    # 2. Filter for user-specific profiles in Python
    # This avoids raw SQL joins and handles child table naming automatically
    result = []
    for p in profiles:
        # Check 'Applicable for Users' child table
        applicable_users = frappe.get_all("POS Profile User", 
            filters={"parent": p.name}, 
            fields=["user"]
        )
        # Match if (list is empty/Global) OR (current user is in the list)
        if not applicable_users or any(u.user == user for u in applicable_users):
            result.append(p)
            
    return result
    # Need a scheduler function which runs every day night that set any checkin that 
    # donot have corresponding checkout (Log Type == "OUT"), 
    # we need to set "custom_no_checkout_found" = 1. 
    # In a day, there can be multiple checkins. frontend is designed such that when a checkin is done, checkout must be done so as to 