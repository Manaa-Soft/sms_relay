app_name = "sms_relay"
app_title = "SMS Relay"
app_publisher = "Manaa-Soft"
app_description = "SMS Relay Gateway for Frappe/ERPNext — multi-device SMS routing with queue management, template rendering, and automated document notifications."
app_email = "manaamnaa2018@gmail.com"
app_license = "apache-2.0"

# Send non-GET requests for this app's endpoints as native `application/json`
# bodies instead of form-encoded, per-key JSON-stringified values.
use_json_request_body = True

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "sms_relay",
# 		"logo": "/assets/sms_relay/logo.png",
# 		"title": "SMS Relay",
# 		"route": "/sms_relay",
# 		"has_permission": "sms_relay.api.permission.has_app_permission",
# 	}
# ]

# Companion apps that extend a host app (instead of taking their own apps-screen icon) can pin
# their workspaces into the host app's workspace dock (rail) with this hook. Declaring it keeps
# the app off the apps screen, so it takes precedence over any add_to_apps_screen above. Who can
# see a pinned workspace is controlled by that workspace's own Roles table.
# add_to_workspace_dock = [
# 	{
# 		"app": "erpnext",
# 		"workspace": "My Workspace",
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/sms_relay/css/sms_relay.css"
app_include_js = "/assets/sms_relay/js/sms_gateway_integration.js"

# include js, css files in header of web template
# web_include_css = "/assets/sms_relay/css/sms_relay.css"
# web_include_js = "/assets/sms_relay/js/sms_relay.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "sms_relay/public/scss/website"

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
# app_include_icons = "sms_relay/public/icons.svg"

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
# 	"methods": "sms_relay.utils.jinja_methods",
# 	"filters": "sms_relay.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "sms_relay.install.before_install"
after_install = "sms_relay.setup.after_install"

# Uninstallation
# ------------

# before_uninstall = "sms_relay.uninstall.before_uninstall"
# after_uninstall = "sms_relay.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "sms_relay.utils.before_app_install"
# after_app_install = "sms_relay.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "sms_relay.utils.before_app_uninstall"
# after_app_uninstall = "sms_relay.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "sms_relay.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "sms_relay.notifications.get_notification_config"

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

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sales Invoice": {
		"on_submit": "sms_relay.handlers.on_invoice_submit",
	},
	"Payment Entry": {
		"on_submit": "sms_relay.handlers.on_payment_submit",
	},
	"Payment Request": {
		"on_submit": "sms_relay.handlers.on_payment_request_submit",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"all": [
		"sms_relay.tasks.process_sms_queue",
	],
	"daily": [
		"sms_relay.tasks.send_balance_reminders",
		"sms_relay.tasks.retry_failed_sms",
		"sms_relay.tasks.cleanup_old_logs",
		"sms_relay.tasks.reset_daily_quotas",
	],
}

# Testing
# -------

# before_tests = "sms_relay.install.before_tests"

# Extend DocType Class
# ------------------------------

# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "sms_relay.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------

override_whitelisted_methods = {
	"frappe.core.doctype.sms_settings.sms_settings.send_sms": "sms_relay.sms_engine.send_sms_override",
}

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "sms_relay.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["sms_relay.utils.before_request"]
# after_request = ["sms_relay.utils.after_request"]

# Job Events
# ----------
# before_job = ["sms_relay.utils.before_job"]
# after_job = ["sms_relay.utils.after_job"]

# after_file_upload = ["sms_relay.utils.after_file_upload"]

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
# 	"sms_relay.auth.validate"
# ]

# Fixtures
# --------

fixtures = [
	{
		"dt": "SMS Gateway Settings",
		"filters": [["name", "!=", ""]],
	},
]

# Website Route Rules (webhook)
# -----------------------------

website_route_rules = [
	{
		"from_route": "/webhook/sms",
		"to_route": "webhook",
		"defaults": {
			"doctype": "SMS Gateway Settings",
		},
	},
]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
