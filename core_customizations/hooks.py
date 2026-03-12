app_name = "core_customizations"
app_title = "Core Customizations"
app_publisher = "Vinod Kumar K"
app_description = "Customization on Core Document Types"
app_email = "vinodkumarkolli@gmail.com"
app_license = "bsd-3-clause"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "core_customizations",
# 		"logo": "/assets/core_customizations/logo.png",
# 		"title": "Core Customizations",
# 		"route": "/core_customizations",
# 		"has_permission": "core_customizations.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/core_customizations/css/core_customizations.css"
# app_include_js = "/assets/core_customizations/js/core_customizations.js"

# include js, css files in header of web template
# web_include_css = "/assets/core_customizations/css/core_customizations.css"
# web_include_js = "/assets/core_customizations/js/core_customizations.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "core_customizations/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "core_customizations/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "core_customizations.utils.jinja_methods",
# 	"filters": "core_customizations.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "core_customizations.install.before_install"
# after_install = "core_customizations.install.after_install"

after_migrate = "core_customizations.setup.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "core_customizations.uninstall.before_uninstall"
# after_uninstall = "core_customizations.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "core_customizations.utils.before_app_install"
# after_app_install = "core_customizations.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "core_customizations.utils.before_app_uninstall"
# after_app_uninstall = "core_customizations.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "core_customizations.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"core_customizations.tasks.all"
# 	],
# 	"daily": [
# 		"core_customizations.tasks.daily"
# 	],
# 	"hourly": [
# 		"core_customizations.tasks.hourly"
# 	],
# 	"weekly": [
# 		"core_customizations.tasks.weekly"
# 	],
# 	"monthly": [
# 		"core_customizations.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "core_customizations.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "core_customizations.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "core_customizations.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["core_customizations.utils.before_request"]
# after_request = ["core_customizations.utils.after_request"]

# Job Events
# ----------
# before_job = ["core_customizations.utils.before_job"]
# after_job = ["core_customizations.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"core_customizations.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
fixtures = [
    {
        "doctype":"Custom Field", "filters":{"module":["in",["Core Customizations"]]}
    },
    {
        "doctype":"Print Format", "filters":{"module":["in",["Core Customizations"]]}
    },
    {
        "doctype":"Client Script", "filters":{"module":["in",["Core Customizations"]]}
    },
    {
        "doctype":"Workflow State", "filters":{"name":["in",["Draft"]]}
    },
    {
        "doctype":"Workflow Action Master", "filters":{"name":["in",["Submit for Review"]]}
    },
    {
        "doctype":"Workflow"
    },
    {
        "doctype": "Supplier Group", "filters": [["name", "in", ["All Supplier Groups","Vendors", "BTL", "INSTALLER", "OOH", "TM"]]]
    }
]
