app_name = "sms_relay"
app_title = "SMS Relay"
app_publisher = "SMS Relay"
app_description = "Frappe/ERPNext SMS Gateway Integration"
app_version = "1.0.0"

app_include_js = [
    "/assets/sms_relay/js/sms_dashboard.js",
    "/assets/sms_relay/js/bulk_message.js",
    "/assets/sms_relay/js/notification_builder.js",
]

doc_events = {
    "*": {
        "before_insert": "sms_relay.utils.notification_handler.on_doc_event",
        "after_insert": "sms_relay.utils.notification_handler.on_doc_event",
        "before_validate": "sms_relay.utils.notification_handler.on_doc_event",
        "validate": "sms_relay.utils.notification_handler.on_doc_event",
        "on_update": "sms_relay.utils.notification_handler.on_doc_event",
        "before_submit": "sms_relay.utils.notification_handler.on_doc_event",
        "on_submit": "sms_relay.utils.notification_handler.on_doc_event",
        "before_cancel": "sms_relay.utils.notification_handler.on_doc_event",
        "on_cancel": "sms_relay.utils.notification_handler.on_doc_event",
        "on_trash": "sms_relay.utils.notification_handler.on_doc_event",
        "after_delete": "sms_relay.utils.notification_handler.on_doc_event",
        "before_update_after_submit": "sms_relay.utils.notification_handler.on_doc_event",
        "on_update_after_submit": "sms_relay.utils.notification_handler.on_doc_event",
    }
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
        "sms_relay.frappe_whatsapp.doctype.sms_notification.sms_notification.trigger_notifications",
    ],
}

after_install = "sms_relay.setup.after_install"
before_tests = "sms_relay.setup.before_tests"
