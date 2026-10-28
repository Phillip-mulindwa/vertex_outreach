app_name = "vertex_outreach"
app_title = "Vertex Outreach"
app_publisher = "Vertex International Recruitment"
app_description = "Outreach email dedup and partner blocking for Vertex International Recruitment"
app_email = "p.mulindwa@alustudent.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "vertex_outreach",
# 		"logo": "/assets/vertex_outreach/logo.png",
# 		"title": "Vertex Outreach",
# 		"route": "/vertex_outreach",
# 		"has_permission": "vertex_outreach.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/vertex_outreach/css/vertex_outreach.css"
app_include_js = "/assets/vertex_outreach/js/check_leads.js"

# include js, css files in header of web template
# web_include_css = "/assets/vertex_outreach/css/vertex_outreach.css"
# web_include_js = "/assets/vertex_outreach/js/vertex_outreach.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "vertex_outreach/public/scss/website"

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
# app_include_icons = "vertex_outreach/public/icons.svg"

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

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "vertex_outreach.utils.jinja_methods",
# 	"filters": "vertex_outreach.utils.jinja_filters"
# }

# Installation
# ------------

before_install = "vertex_outreach.install.ensure_role"
before_migrate = "vertex_outreach.install.ensure_role"
after_install = "vertex_outreach.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "vertex_outreach.uninstall.before_uninstall"
# after_uninstall = "vertex_outreach.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "vertex_outreach.utils.before_app_install"
# after_app_install = "vertex_outreach.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "vertex_outreach.utils.before_app_uninstall"
# after_app_uninstall = "vertex_outreach.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "vertex_outreach.notifications.get_notification_config"

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

scheduler_events = {
	"daily": ["vertex_outreach.contacts.release_stale_claims"],
}

# scheduler_events = {
# 	"all": [
# 		"vertex_outreach.tasks.all"
# 	],
# 	"daily": [
# 		"vertex_outreach.tasks.daily"
# 	],
# 	"hourly": [
# 		"vertex_outreach.tasks.hourly"
# 	],
# 	"weekly": [
# 		"vertex_outreach.tasks.weekly"
# 	],
# 	"monthly": [
# 		"vertex_outreach.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "vertex_outreach.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "vertex_outreach.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "vertex_outreach.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["vertex_outreach.utils.before_request"]
# after_request = ["vertex_outreach.utils.after_request"]

# Job Events
# ----------
# before_job = ["vertex_outreach.utils.before_job"]
# after_job = ["vertex_outreach.utils.after_job"]

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
# 	"vertex_outreach.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
