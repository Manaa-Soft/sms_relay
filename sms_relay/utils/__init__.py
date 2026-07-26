"""SMS Relay notification dispatch — mirrors frappe_whatsapp.utils pattern."""
import frappe

from frappe.core.doctype.server_script.server_script_utils import EVENT_MAP


def run_server_script_for_doc_event(doc, event):
    """Run on each doc event — entry point for doc_events['*']."""
    if event not in EVENT_MAP:
        return
    if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_uninstall:
        return

    notification = get_notifications_map().get(
        doc.doctype, {}
    ).get(EVENT_MAP[event], None)

    if notification:
        for notification_name in notification:
            _schedule_sms_notification(notification_name, doc)


def _schedule_sms_notification(notification_name, doc):
    """Schedule SMS notification to run after commit (Frappe v16 pattern)."""
    if hasattr(frappe.db, "after_commit"):
        frappe.db.after_commit.add(
            lambda: _send_sms_notification(
                notification_name, doc.doctype, doc.name, commit=True
            )
        )
    else:
        _send_sms_notification(notification_name, doc.doctype, doc.name)


def _send_sms_notification(notification_name, doctype, docname, commit=False):
    """Send SMS notification."""
    try:
        doc = frappe.get_doc(doctype, docname)
        frappe.get_doc(
            "SMS Notification",
            notification_name
        ).send_template_message(doc)
        if commit:
            frappe.db.commit()
    except Exception:
        if commit:
            frappe.db.rollback()
        frappe.log_error(
            title="SMS Notification failed: {}".format(notification_name)
        )


def get_notifications_map():
    """Build and cache a map: {doctype: {event: [notification_name, ...]}}."""
    if frappe.flags.in_patch and not frappe.db.table_exists("SMS Notification"):
        return {}

    notification_map = {}
    enabled_notifications = frappe.get_all(
        "SMS Notification",
        fields=("name", "reference_doctype", "doctype_event", "notification_type"),
        filters={"disabled": 0},
    )
    for notification in enabled_notifications:
        if notification.notification_type == "DocType Event":
            notification_map.setdefault(
                notification.reference_doctype, {}
            ).setdefault(
                notification.doctype_event, []
            ).append(notification.name)

    frappe.cache().set_value("sms_notification_map", notification_map)
    return notification_map


# ─── Scheduler triggers ──────────────────────────────────────────────

def trigger_sms_notifications_all():
    trigger_sms_notifications("All")

def trigger_sms_notifications_hourly():
    trigger_sms_notifications("Hourly")

def trigger_sms_notifications_daily():
    trigger_sms_notifications("Daily")

def trigger_sms_notifications_weekly():
    trigger_sms_notifications("Weekly")

def trigger_sms_notifications_monthly():
    trigger_sms_notifications("Monthly")

def trigger_sms_notifications_yearly():
    trigger_sms_notifications("Yearly")


def trigger_sms_notifications(event):
    """Run cron — find all scheduler notifications with this frequency."""
    sms_notify_list = frappe.get_list(
        "SMS Notification",
        filters={
            "event_frequency": event,
            "disabled": 0,
            "notification_type": "Scheduler Event",
        }
    )
    for notif in sms_notify_list:
        frappe.get_doc(
            "SMS Notification",
            notif.name,
        ).send_scheduled_message()
