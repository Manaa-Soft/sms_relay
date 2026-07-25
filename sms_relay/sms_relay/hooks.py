app_name = "sms_relay"
app_title = "SMS Relay"
app_publisher = "Manaa Soft"
app_description = "SMS Relay Gateway for Frappe/ERPNext - Multi-device SMS routing with queue management"
app_version = "1.0.0"
app_color = "#4a90d9"
app_icon = "octicon octicon-device-mobile"
app_email = "info@manaa-soft.com"
app_license = "Apache-2.0"

# ---------------------
# Send SMS Hook
# ---------------------
send_sms = "sms_relay.sms_engine.send_sms"

# ---------------------
# Doc Events
# ---------------------
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

# ---------------------
# Scheduler Events
# ---------------------
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

# ---------------------
# Override Whitelisted Methods
# ---------------------
override_whitelisted_methods = {
    "frappe.core.doctype.sms_settings.sms_settings.send_sms": "sms_relay.sms_engine.send_sms_override",
}

# ---------------------
# Install / Uninstall
# ---------------------
after_install = "sms_relay.setup.after_install"

# ---------------------
# Fixtures
# ---------------------
fixtures = [
    {
        "dt": "SMS Gateway Settings",
        "filters": [["name", "!=", ""]],
    },
]

# ---------------------
# Website Route Rules (webhook)
# ---------------------
website_route_rules = [
    {
        "from_route": "/webhook/sms",
        "to_route": "webhook",
        "defaults": {
            "doctype": "SMS Gateway Settings",
        },
    },
]

# ---------------------
# App Include
# ---------------------
app_include_js = "/assets/sms_relay/js/sms_gateway_integration.js"
