import json
import frappe
from frappe import _
from frappe.utils import cint, now

@frappe.whitelist(allow_guest=True)
def incoming_webhook():
    try:
        payload = frappe.request.get_data(as_text=True)
        data = json.loads(payload)
    except Exception:
        frappe.throw(_("Invalid JSON payload"), frappe.ValidationError)
        return

    settings = frappe.get_single("SMS Gateway Settings")
    secret = settings.get_password("webhook_secret") if hasattr(settings, "webhook_secret") else None
    if secret:
        from sms_relay.core.sms_utils import verify_webhook_signature
        signature = frappe.get_request_header("X-Webhook-Signature")
        if not verify_webhook_signature(payload.encode("utf-8"), secret, signature):
            frappe.throw(_("Invalid webhook signature"), frappe.ValidationError)
            return

    event_type = data.get("event") or data.get("type") or ""

    if event_type == "system:ping":
        return {"status": "ok"}

    if event_type in ("sms:delivered", "sms:sent", "sms:failed"):
        _handle_delivery_report(data, event_type)
        return {"status": "processed"}

    if event_type == "sms:cancelled":
        _handle_cancelled_report(data)
        return {"status": "processed"}

    if event_type in ("sms:received", "incoming"):
        _handle_incoming_sms(data)
        return {"status": "processed"}

    phone = data.get("phone") or data.get("from") or data.get("phoneNumber")
    message = data.get("message") or data.get("text") or data.get("body")
    if phone and message:
        _handle_incoming_sms(data)
        return {"status": "processed"}

    frappe.log_error(
        title="SMS Webhook: Unknown event type: {}".format(event_type),
    )
    return {"status": "ignored"}

def _handle_delivery_report(data, event_type):
    message_id = data.get("id") or data.get("messageId") or data.get("message_id")
    status_map = {
        "sms:delivered": "Delivered",
        "sms:sent": "Sent",
        "sms:failed": "Failed",
    }
    new_status = status_map.get(event_type, "Sent")

    if message_id:
        frappe.db.set_value("SMS Queue", {"name": message_id}, "status", new_status)
        frappe.db.set_value("SMS Log", {"gateway_message_id": message_id}, "delivery_status", new_status)
        frappe.db.commit()

    _idempotency_check(data, "delivery_report")

def _handle_cancelled_report(data):
    message_id = data.get("id") or data.get("messageId") or data.get("message_id")
    if message_id:
        frappe.db.set_value("SMS Queue", {"gateway_message_id": message_id}, "status", "Cancelled")
        frappe.db.set_value("SMS Log", {"gateway_message_id": message_id}, "status", "Cancelled")
        frappe.db.commit()

def _enqueue_webhook_delivery(url, payload, headers=None):
    """Enqueue a webhook delivery with exponential backoff retry."""
    settings = frappe.get_single("SMS Gateway Settings")
    max_retries = cint(settings.get("webhook_max_retries")) or 15
    base_delay = cint(settings.get("webhook_base_delay")) or 30

    try:
        frappe.get_doc({
            "doctype": "SMS Webhook Delivery",
            "url": url,
            "payload": json.dumps(payload) if isinstance(payload, dict) else payload,
            "headers": json.dumps(headers) if headers else None,
            "status": "Pending",
            "attempts": 0,
            "max_attempts": max_retries,
            "next_retry_at": frappe.utils.now_datetime(),
            "base_delay": base_delay,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        pass

def _handle_incoming_sms(data):
    phone = data.get("phone") or data.get("from") or data.get("phoneNumber") or ""
    message = data.get("message") or data.get("text") or data.get("body") or ""
    profile_name = data.get("profileName") or data.get("contact_name") or ""
    device_id = data.get("deviceId") or data.get("device_id") or ""

    if not phone or not message:
        return

    if _idempotency_check(data, "incoming"):
        return

    from sms_relay.utils.contact_manager import create_communication
    message_doc = {"message": message, "phone": phone, "received_at": now()}
    create_communication(message_doc, phone, profile_name)

    queue = frappe.new_doc("SMS Queue")
    queue.recipient = phone
    queue.message = message
    queue.status = "Received"
    queue.insert(ignore_permissions=True)

    frappe.db.commit()

def _idempotency_check(data, prefix):
    cache_key = "webhook_{}_{}".format(prefix, hash(json.dumps(data, sort_keys=True)))
    if frappe.cache().get_value(cache_key):
        return True
    frappe.cache().set_value(cache_key, True, expires_in_sec=300)
    return False
