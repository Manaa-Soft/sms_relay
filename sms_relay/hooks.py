app_name = "sms_relay"
app_title = "SMS Relay"
app_publisher = "Manaa-Soft"
app_description = "SMS Relay Gateway for Frappe/ERPNext — multi-device SMS routing with queue management, template rendering, and automated document notifications."
app_email = "manaamnaa2018@gmail.com"
app_license = "apache-2.0"

use_json_request_body = True

# Includes in <head>
# ------------------

app_include_js = "/assets/sms_relay/js/sms_gateway_integration.js"
# app_include_css = "/assets/sms_relay/css/sms_relay.css"

# Installation
# ------------

after_install = "sms_relay.setup.after_install"

# Document Events
# ---------------

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

# Overriding Methods
# ------------------

override_whitelisted_methods = {
	"frappe.core.doctype.sms_settings.sms_settings.send_sms": "sms_relay.sms_engine.send_sms_override",
}

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

export_python_type_annotations = True
require_type_annotated_api_methods = True
