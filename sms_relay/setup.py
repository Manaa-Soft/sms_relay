"""Post-installation setup for the SMS Relay module.

This module is executed automatically by Frappe after the ``sms_relay`` app is
installed (via the ``after_install`` hook). It bootstraps the module with safe
default configuration so that administrators can begin using the system
immediately without manual data entry.

Actions performed on install:
    1. Creates the ``SMS Gateway Settings`` singleton document with all
       features disabled, an empty gateway URL, sensible retry and rate-limit
       values, and a default sender name of ``"SMSRelay"``. No gateway
       credentials are stored -- the administrator must configure them
       afterwards.
    2. Creates four default ``SMS Template`` documents for common ERPNext
       workflows: Invoice Notification, Payment Received, Payment Request, and
       Overdue Reminder. Each template uses Jinja2 syntax with placeholder
       variables that are populated at send time.

All inserts use ``ignore_permissions=True`` because this code runs during the
Frappe migration/install context where permission checks are not applicable.
Existing documents are never overwritten.
"""

import frappe


def after_install():
    """Entry point called by Frappe after the ``sms_relay`` app is installed.

    Orchestrates the one-time setup of the SMS Relay module by delegating to
    two private helpers that create the gateway settings singleton and the
    default SMS templates.

    Returns:
        None
    """
    _create_gateway_settings()
    _create_sms_templates()


def _create_gateway_settings():
    """Create the ``SMS Gateway Settings`` singleton with safe default values.

    If the singleton already exists the function returns immediately without
    making any changes. The created document has all SMS-triggering features
    disabled (``send_invoice_sms``, ``send_payment_sms``,
    ``send_payment_request_sms``, ``send_overdue_reminders`` are all ``0``)
    and ``enabled`` set to ``0`` so the gateway is inactive until explicitly
    configured and turned on by an administrator.

    Default values:
        - ``default_sender``: ``"SMSRelay"``
        - ``reminder_intervals``: ``"7,14,30,60,90"``
        - ``max_retry_count``: ``3``
        - ``rate_limit``: ``30``

    Returns:
        None
    """
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
    """Create default SMS Template documents for common ERPNext events.

    Four templates are created if they do not already exist:

    1. **Invoice Notification** (``invoice_template``) -- Sent when a new
       sales invoice is created. Contains customer name, invoice ID, total,
       due date, and outstanding amount placeholders.
    2. **Payment Received** (``payment_template``) -- Sent when a payment is
       recorded. Contains party name, amount, posting date, and payment
       reference placeholders.
    3. **Payment Request** (``payment_request_template``) -- Sent when a
       payment request is created. Contains party name, amount, and payment
       URL placeholders.
    4. **Overdue Reminder** (``overdue_template``) -- Sent for overdue
       invoices. Contains customer name, invoice count, outstanding total,
       days overdue, and invoice reference list placeholders.

    Each template body uses Jinja2 syntax (``{{ variable }}``) and is stored
    as the ``body`` field of an ``SMS Template`` document.

    Returns:
        None
    """
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
