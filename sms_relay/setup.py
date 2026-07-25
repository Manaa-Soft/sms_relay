import frappe


def after_install():
    """Create default SMS Gateway Settings and SMS Templates after app install."""
    _create_gateway_settings()
    _create_sms_templates()


def _create_gateway_settings():
    """Create the SMS Gateway Settings singleton with sensible defaults."""
    if frappe.db.exists("SMS Gateway Settings", "SMS Gateway Settings"):
        return

    settings = frappe.get_doc({
        "doctype": "SMS Gateway Settings",
        "enabled": 0,
        "gateway_url": "",
        "api_key": "",
        "api_secret": "",
        "webhook_secret": "",
        "default_sender": "SMSRelay",
        "send_invoice_sms": 0,
        "send_payment_sms": 0,
        "send_payment_request_sms": 0,
        "send_overdue_reminders": 0,
        "reminder_intervals": "7,14,30,60,90",
        "max_retry_count": 3,
        "rate_limit": 30,
    })

    try:
        settings.insert(ignore_permissions=True)
        frappe.db.commit()
        frappe.msgprint("SMS Gateway Settings created")
    except Exception as e:
        frappe.log_error(f"SMS Relay: failed to create gateway settings: {e}")


def _create_sms_templates():
    """Create default SMS templates for invoice, payment, overdue, and payment request."""
    templates = [
        {
            "template_name": "Invoice Notification",
            "template_key": "invoice_template",
            "body": (
                "Dear {{ customer_name }}, your invoice {{ invoice_name }} "
                "for {{ total }} is due on {{ due_date }}. "
                "Outstanding: {{ outstanding }}. Thank you!"
            ),
        },
        {
            "template_name": "Payment Received",
            "template_key": "payment_template",
            "body": (
                "Dear {{ party_name }}, payment of {{ amount }} "
                "has been received on {{ posting_date }}. "
                "Ref: {{ payment_name }}. Thank you!"
            ),
        },
        {
            "template_name": "Payment Request",
            "template_key": "payment_request_template",
            "body": (
                "Dear {{ party_name }}, a payment of {{ amount }} "
                "has been requested. Please complete payment using the link: {{ payment_url }}"
            ),
        },
        {
            "template_name": "Overdue Reminder",
            "template_key": "overdue_template",
            "body": (
                "Dear {{ customer_name }}, you have {{ invoice_count }} overdue "
                "invoice(s) totaling {{ outstanding_total }} "
                "(overdue {{ days_overdue }} days). Please arrange payment. "
                "Invoice(s): {{ invoice_names }}"
            ),
        },
    ]

    for tmpl in templates:
        if frappe.db.exists("SMS Template", tmpl["template_name"]):
            continue

        try:
            doc = frappe.get_doc({
                "doctype": "SMS Template",
                "template_name": tmpl["template_name"],
                "body": tmpl["body"],
            })
            doc.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"SMS Relay: failed to create template '{tmpl['template_name']}': {e}")

    frappe.db.commit()
