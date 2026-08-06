import frappe

def after_install():
    _create_default_gateway_settings()
    _create_default_templates()
    _create_default_notifications()

def _create_default_gateway_settings():
    if not frappe.db.exists("SMS Gateway Settings", "SMS Gateway Settings"):
        settings = frappe.new_doc("SMS Gateway Settings")
        settings.routing_strategy = "Round Robin"
        settings.failover_enabled = 1
        settings.global_rate_limit = 60
        settings.insert(ignore_permissions=True)
        frappe.db.commit()

def _get_language_doc(lang_code, fallback):
    """Resolve a Language doc name by language_code with a fallback name."""
    name = frappe.db.get_value("Language", {"language_code": lang_code}, "name")
    return name or fallback

def _create_default_templates():
    try:
        _seed_default_templates()
    except Exception as e:
        frappe.log_error(f"Failed to seed SMS Templates: {e}", "sms_relay.setup")

def _seed_default_templates():
    en = _get_language_doc("en", "English")
    ar = _get_language_doc("ar", "العربية")
    templates = [
        {
            "template_name": "Payment Reminder",
            "category": "UTILITY",
            "language": en,
            "message_template": "Dear {{ doc.customer }}, your invoice {{ doc.name }} for {{ frappe.utils.fmt_money(doc.outstanding_amount) }} is overdue. Please pay at your earliest convenience.",
        },
        {
            "template_name": "Order Confirmation",
            "category": "TRANSACTIONAL",
            "language": en,
            "message_template": "Thank you for your order {{ doc.name }}. Total: {{ frappe.utils.fmt_money(doc.grand_total) }}. We will process your order shortly.",
        },
        {
            "template_name": "Dispatch Notification",
            "category": "TRANSACTIONAL",
            "language": en,
            "message_template": "Your order {{ doc.name }} has been dispatched. Expected delivery: {{ doc.delivery_date }}. Tracking will be shared shortly.",
        },
        {
            "template_name": "Payment Link",
            "category": "TRANSACTIONAL",
            "language": en,
            "message_template": "Dear {{ doc.customer }}, pay your invoice {{ doc.name }} ({{ frappe.utils.fmt_money(doc.grand_total) }}) using this link: {{ doc.payment_url }}",
        },
        {
            "template_name": "Overdue Invoice Reminder",
            "category": "UTILITY",
            "language": en,
            "message_template": "Dear {{ doc.customer }} - Reminder: Invoice {{ doc.name }} is overdue (due {{ frappe.utils.formatdate(doc.due_date) }}). Outstanding: {{ frappe.utils.fmt_money(doc.outstanding_amount) }}. Please pay soon.",
        },
        {
            "template_name": "Overdue Invoice Reminder (Arabic)",
            "category": "UTILITY",
            "language": ar,
            "message_template": "عزيزي {{ doc.customer }}، تذكير: الفاتورة {{ doc.name }} متأخرة السداد (تاريخ الاستحقاق {{ frappe.utils.formatdate(doc.due_date) }}). المبلغ المستحق: {{ frappe.utils.fmt_money(doc.outstanding_amount) }}. يرجى الدفع في أقرب وقت.",
        },
        {
            "template_name": "Payment Reminder (Arabic)",
            "category": "UTILITY",
            "language": ar,
            "message_template": "عزيزي {{ doc.customer }}، فاتورتك {{ doc.name }} بمبلغ {{ frappe.utils.fmt_money(doc.outstanding_amount) }} متأخرة السداد. يرجى الدفع في أقرب وقت ممكن.",
        },
        {
            "template_name": "Order Confirmation (Arabic)",
            "category": "TRANSACTIONAL",
            "language": ar,
            "message_template": "شكراً لطلبك {{ doc.name }}. الإجمالي: {{ frappe.utils.fmt_money(doc.grand_total) }}. سنقوم بمعالجة طلبك قريباً.",
        },
        {
            "template_name": "Dispatch Notification (Arabic)",
            "category": "TRANSACTIONAL",
            "language": ar,
            "message_template": "تم شحن طلبك {{ doc.name }}. التسليم المتوقع: {{ doc.delivery_date }}. سيتم مشاركة رقم التتبع قريباً.",
        },
        {
            "template_name": "Payment Link (Arabic)",
            "category": "TRANSACTIONAL",
            "language": ar,
            "message_template": "عزيزي {{ doc.customer }}، ادفع فاتورتك {{ doc.name }} ({{ frappe.utils.fmt_money(doc.grand_total) }}) عبر هذا الرابط: {{ doc.payment_url }}",
        },
    ]
    for t in templates:
        if not frappe.db.exists("SMS Template", t["template_name"]):
            doc = frappe.new_doc("SMS Template")
            doc.update(t)
            doc.insert(ignore_permissions=True)
    frappe.db.commit()

def _create_default_notifications():
    try:
        _seed_default_notifications()
    except Exception as e:
        frappe.log_error(f"Failed to seed SMS Notifications: {e}", "sms_relay.setup")

def _seed_default_notifications():
    notifications = [
        {
            "notification_name": "Send Overdue Invoice Reminders",
            "notification_type": "DocType Event",
            "reference_doctype": "Sales Invoice",
            "doctype_event": "After Submit",
            "field_name": "contact_mobile",
            "template": "Overdue Invoice Reminder",
            "template_type": "Jinja",
            "disabled": 0,
        },
        {
            "notification_name": "Send Payment Reminder",
            "notification_type": "DocType Event",
            "reference_doctype": "Sales Invoice",
            "doctype_event": "After Submit",
            "field_name": "contact_mobile",
            "template": "Payment Reminder",
            "template_type": "Jinja",
            "disabled": 1,
        },
        {
            "notification_name": "Send Order Confirmation",
            "notification_type": "DocType Event",
            "reference_doctype": "Sales Order",
            "doctype_event": "After Submit",
            "field_name": "contact_mobile",
            "template": "Order Confirmation",
            "template_type": "Jinja",
            "disabled": 1,
        },
        {
            "notification_name": "Send Dispatch Notification",
            "notification_type": "DocType Event",
            "reference_doctype": "Delivery Note",
            "doctype_event": "After Submit",
            "field_name": "contact_mobile",
            "template": "Dispatch Notification",
            "template_type": "Jinja",
            "disabled": 1,
        },
        {
            "notification_name": "Send Payment Link",
            "notification_type": "DocType Event",
            "reference_doctype": "Sales Invoice",
            "doctype_event": "After Submit",
            "field_name": "contact_mobile",
            "template": "Payment Link",
            "template_type": "Jinja",
            "disabled": 1,
        },
    ]
    for n in notifications:
        if not frappe.db.exists("SMS Notification", n["notification_name"]):
            doc = frappe.new_doc("SMS Notification")
            doc.update(n)
            doc.insert(ignore_permissions=True)
    frappe.db.commit()

def after_migrate():
    """Run after every `bench migrate` — keeps the app visible on the desk and
    (re)seeds default SMS Templates and Notifications for existing installs.

    Seeding is idempotent: records already present (or edited/disabled by the
    user) are left untouched.

    Frappe v16+ has two desk home modes (`Desktop Settings -> Desktop Page`):

    - **Apps** (default on fresh installs, hook-driven): sms_relay appears because it
      declares the `add_to_apps_screen` hook, so nothing is needed here.
    - **Desktop Icons** (older/upgraded sites are switched here by the frappe v16 patch
      `keep_existing_sites_on_desktop_icons`): the grid is drawn from the `Desktop Icon`
      doctype, and icons are only seeded while an app is *installed* in that mode. sms_relay
      ships no `desktop_icons/` fixture, so on upgraded sites it dropped off the desk.

    Seeding the icon here (idempotent, a no-op in Apps mode) keeps the app visible whichever
    mode the site uses. Falls back silently on Frappe versions without the seeding API.
    """
    _create_default_templates()
    _create_default_notifications()
    _upgrade_seeded_notifications()
    _ensure_sms_relay_desktop_icon()


def _upgrade_seeded_notifications():
    """Convert legacy seeded overdue notifications to DocType Event.

    Earlier seeds created "Send Overdue Invoice Reminders" and "Send Payment
    Reminder" as daily Scheduler Events. Existing records are upgraded here to
    a DocType Event (After Submit) with the doctype's phone field connected
    (``contact_mobile``). Disabled and template choices are preserved.
    """
    names = ("Send Overdue Invoice Reminders", "Send Payment Reminder")
    for name in names:
        if not frappe.db.exists("SMS Notification", name):
            continue
        try:
            doc = frappe.get_doc("SMS Notification", name)
            needs_fix = (
                doc.notification_type != "DocType Event"
                or not doc.field_name
                or doc.get("scheduler_data_source")
            )
            if not needs_fix:
                continue
            doc.notification_type = "DocType Event"
            doc.doctype_event = "After Submit"
            doc.field_name = "contact_mobile"
            doc.scheduler_data_source = ""
            doc.event_frequency = ""
            doc.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Failed to upgrade notification {name}: {e}", "sms_relay.setup")
    frappe.db.commit()


def _ensure_sms_relay_desktop_icon():
    try:
        from frappe.utils.install import create_desktop_icons_for_app
    except ImportError:
        return
    try:
        create_desktop_icons_for_app("sms_relay")
    except Exception as e:
        frappe.log_error(f"Failed to seed SMS Relay desktop icon: {e}", "sms_relay.setup.after_migrate")

def before_tests():
    pass
