import frappe
from frappe import _
from frappe.utils import now
from sms_relay.core.sms_utils import clean_phone, get_relay_settings, is_opted_out

DOCTYPE_EVENT_MAP = {
    "Before Insert": "before_insert",
    "After Insert": "after_insert",
    "Save": "on_update",
    "Submit": "on_submit",
    "Cancel": "on_cancel",
    "Trash": "on_trash",
    "After Save": "on_update",
    "Before Save": "before_validate",
    "Modified": "on_update",
    "Value Changed": "on_update",
    "Scheduled Task": "on_update",
    "Booking Created": "on_update",
    "Authorization": "on_update",
}

SCHEDULER_FREQUENCY_MAP = {
    "All": "all",
    "Hourly": "hourly",
    "Daily": "daily",
    "Weekly": "weekly",
    "Monthly": "monthly",
    "Yearly": "yearly",
}


def on_doc_event(doc, method):
    notifications = frappe.get_all(
        "SMS Notification",
        filters={"disabled": 0, "reference_doctype": doc.doctype, "notification_type": "DocType Event"},
        fields=["name"],
    )
    for notif in notifications:
        try:
            _process_notification(notif.name, doc, method)
        except Exception:
            frappe.log_error(
                title="SMS Notification Error: {}".format(notif.name),
            )


def on_scheduler_event(frequency):
    freq_key = {v: k for k, v in SCHEDULER_FREQUENCY_MAP.items()}.get(frequency, frequency)
    notifications = frappe.get_all(
        "SMS Notification",
        filters={"disabled": 0, "notification_type": "Scheduler Event", "event_frequency": freq_key},
        fields=["name"],
    )
    for notif in notifications:
        try:
            doc = _get_scheduler_doc(notif.name)
            if doc:
                _process_notification(notif.name, doc, "scheduler")
        except Exception:
            frappe.log_error(title="SMS Scheduler Error: {}".format(notif.name))


def _get_scheduler_doc(notification_name):
    notification = frappe.get_doc("SMS Notification", notification_name)
    if notification.send_on:
        return frappe.new_doc(notification.reference_doctype)
    return frappe.new_doc(notification.reference_doctype)


def _process_notification(notification_name, doc, method):
    notification = frappe.get_doc("SMS Notification", notification_name)
    if notification.notification_type == "DocType Event" and not _check_event_match(notification, method):
        return
    if not _should_send(notification, doc):
        return
    phone = _get_phone_number(notification, doc)
    if not phone:
        return
    cleaned = clean_phone(phone)
    if is_opted_out(cleaned):
        return
    message = _render_notification(notification, doc)
    if not message:
        return
    _send_notification_sms(notification, doc, cleaned, message)
    _log_notification(notification, doc, cleaned, message, "Sent")
    _set_property_after_alert(notification, doc)


def _check_event_match(notification, method):
    expected = DOCTYPE_EVENT_MAP.get(notification.doctype_event, "on_submit")
    return method == expected


def _should_send(notification, doc):
    if not notification.condition:
        return True
    try:
        condition_locals = {"doc": doc, "frappe": frappe}
        result = frappe.safe_eval(notification.condition, condition_locals)
        return bool(result)
    except Exception:
        return False


def _get_phone_number(notification, doc):
    field_name = notification.field_name
    if field_name:
        phone_value = doc.get(field_name)
        if phone_value:
            return str(phone_value)
    customer = doc.get("customer") or doc.get("party_name")
    if customer:
        from sms_relay.core.sms_engine import _get_customer_phone
        phone = _get_customer_phone(customer)
        if phone:
            return phone
    supplier = doc.get("supplier")
    if supplier:
        from sms_relay.core.sms_engine import _get_supplier_phone
        phone = _get_supplier_phone(supplier)
        if phone:
            return phone
    return None


def _render_notification(notification, doc):
    if notification.template:
        return _render_from_template(notification, doc)
    message_template = notification.message_template
    if not message_template:
        return ""
    from jinja2 import Template
    tmpl = Template(message_template)
    context = {"doc": doc, "frappe": frappe}
    try:
        return tmpl.render(**context).strip()
    except Exception:
        return ""


def _render_from_template(notification, doc):
    try:
        template_doc = frappe.get_doc("SMS Template", notification.template)
        body = template_doc.message_template or ""
        if not body:
            return ""
        from jinja2 import Template
        tmpl = Template(body)
        context = {"doc": doc, "frappe": frappe}
        return tmpl.render(**context).strip()
    except Exception:
        return ""


def _send_notification_sms(notification, doc, phone, message):
    from sms_relay.core.sms_engine import _enqueue_sms
    priority = "High" if "payment" in message.lower() or "otp" in message.lower() else "Normal"
    queue = _enqueue_sms(
        phone=phone,
        message=message,
        priority=priority,
    )
    return queue


def _log_notification(notification, doc, phone, message, status):
    log = frappe.new_doc("SMS Notification Log")
    log.notification = notification.name
    log.reference_doctype = doc.doctype
    log.reference_name = doc.name
    log.phone = phone
    log.message = message
    log.status = status
    log.sent_at = now()
    log.insert(ignore_permissions=True)
    frappe.db.commit()


def _set_property_after_alert(notification, doc):
    if not notification.set_property_after_alert or notification.set_property_after_alert == "None":
        return
    prop_name = notification.property_name
    prop_value = notification.property_value
    if not prop_name:
        return
    try:
        doc.set(prop_name, prop_value)
        doc.db_update()
        frappe.db.commit()
    except Exception:
        pass
