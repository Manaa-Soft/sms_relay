app_name = "sms_relay"
app_title = "SMS Relay"
app_publisher = "SMS Relay"
app_description = "Frappe/ERPNext SMS Gateway Integration"
app_version = "1.0.0"

app_include_css = None
app_include_js = [
    "/assets/sms_relay/js/sms_dashboard.js",
    "/assets/sms_relay/js/bulk_message.js",
    "/assets/sms_relay/js/notification_builder.js",
]

jinja = {
    "methods": "sms_relay.utils.jinja_methods.get_methods",
}

doc_events = {
    "Sales Invoice": {
        "on_submit": "sms_relay.core.notification_handler.on_doc_event",
    },
    "Payment Request": {
        "on_submit": "sms_relay.core.notification_handler.on_doc_event",
    },
    "Delivery Note": {
        "on_submit": "sms_relay.core.notification_handler.on_doc_event",
    },
    "Purchase Order": {
        "on_submit": "sms_relay.core.notification_handler.on_doc_event",
    },
    "Employee Checkin": {
        "on_insert": "sms_relay.core.notification_handler.on_doc_event",
    },
}

scheduler_events = {
    "all": [
        "sms_relay.tasks.process_sms_queue",
        "sms_relay.tasks.process_outbox",
        "sms_relay.tasks.process_bulk_messages",
    ],
    "hourly": [
        "sms_relay.tasks.check_device_health",
    ],
    "daily": [
        "sms_relay.tasks.send_overdue_reminders",
        "sms_relay.tasks.retry_failed_sms",
        "sms_relay.tasks.cleanup_old_logs",
        "sms_relay.tasks.reset_daily_quotas",
    ],
}

override_whitelisted_methods = {
    "frappe.core.doctype.sms_settings.sms_settings.send_sms": "sms_relay.core.sms_engine.send_sms_override",
}

website_route_rules = [
    {
        "from_route": "/sms/webhook",
        "to_route": "sms/webhook",
    },
]

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "SMS Relay"]],
    },
    {
        "dt": "Property Setter",
        "filters": [["module", "=", "SMS Relay"]],
    },
]

after_install = "sms_relay.setup.after_install"
before_tests = "sms_relay.setup.before_tests"
