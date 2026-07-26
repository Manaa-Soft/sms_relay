import frappe
from frappe import _
from frappe.utils import now
from sms_relay.core.sms_utils import clean_phone, get_relay_settings, is_opted_out

def on_doc_event(doc, method):
    notifications = frappe.get_all(
        "SMS Notification",
        filters={"enabled": 1, "reference_doctype": doc.doctype},
        fields=["name"],
    )
    for notif in notifications:
        try:
            _process_notification(notif.name, doc, method)
        except Exception:
            frappe.log_error(
                title="SMS Notification Error: {}".format(notif.name),
            )

def _process_notification(notification_name, doc, method):
    notification = frappe.get_doc("SMS Notification", notification_name)
    if not _check_event_match(notification, method):
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
    event_map = {
        "On Submit": "on_submit",
        "On Save": "on_save",
        "On Validate": "validate",
    }
    expected = event_map.get(notification.event, "on_submit")
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
    phone_field = notification.phone_field
    if phone_field:
        phone_value = doc.get(phone_field)
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

def _send_notification_sms(notification, doc, phone, message):
    from sms_relay.core.sms_engine import _enqueue_sms, _log_sms
    priority = "High" if "payment" in (notification.message_template or "").lower() or "otp" in (notification.message_template or "").lower() else "Normal"
    queue = _enqueue_sms(
        phone=phone,
        message=message,
        device_name=notification.account,
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
    if not notification.set_property_after_alert:
        return
    try:
        doc.set(notification.set_property_after_alert, notification.property_value)
        doc.db_update()
        frappe.db.commit()
    except Exception:
        pass
