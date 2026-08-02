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
        from sms_relay.core.sms_utils import verify_webhook_signature, verify_gateway_signature
        payload_bytes = payload.encode("utf-8")

        # Legacy scheme: HMAC-SHA256 over raw body, header `X-Webhook-Signature`
        legacy_sig = frappe.get_request_header("X-Webhook-Signature")
        valid = bool(legacy_sig) and verify_webhook_signature(payload_bytes, secret, legacy_sig)

        # Android SMS Gateway app scheme: HMAC-SHA256 over body+timestamp,
        # headers `X-Signature` and `X-Timestamp`
        if not valid:
            gw_sig = frappe.get_request_header("X-Signature")
            gw_ts = frappe.get_request_header("X-Timestamp")
            valid = verify_gateway_signature(payload_bytes, secret, gw_sig, gw_ts)

        if not valid:
            frappe.throw(_("Invalid webhook signature"), frappe.ValidationError)
            return

    event_type = data.get("event") or data.get("type") or ""

    if event_type == "system:ping":
        return {"status": "ok"}

    if event_type == "app:started":
        _handle_app_started(data)
        return {"status": "processed"}

    if event_type in ("sms:delivered", "sms:sent", "sms:failed"):
        _handle_delivery_report(data, event_type)
        return {"status": "processed"}

    if event_type == "sms:cancelled":
        _handle_cancelled_report(data)
        return {"status": "processed"}

    if event_type in ("sms:received", "sms:data-received", "mms:received", "mms:downloaded", "incoming"):
        _handle_incoming_sms(data, event_type)
        return {"status": "processed"}

    phone = data.get("sender") or data.get("phone") or data.get("from") or data.get("phoneNumber")
    message = data.get("message") or data.get("text") or data.get("body") or data.get("subject") or data.get("data")
    if phone and message:
        _handle_incoming_sms(data, event_type)
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

    if _is_duplicate_webhook(data, "delivery_report_{}".format(event_type)):
        return

    if message_id:
        frappe.db.set_value("SMS Queue", {"name": message_id}, "status", new_status)
        log_name = frappe.db.get_value("SMS Log", {"gateway_message_id": message_id}, "name")
        if log_name:
            fields = {
                "delivery_status": new_status,
                "delivery_at": now(),
            }
            if event_type == "sms:failed":
                reason = data.get("reason") or data.get("error")
                if reason:
                    fields["error_message"] = reason
            if event_type == "sms:sent":
                parts = data.get("partsCount")
                if parts is not None:
                    fields["sms_parts"] = cint(parts)
            frappe.db.set_value("SMS Log", log_name, fields)
        frappe.db.commit()

    _mark_webhook_seen(data, "delivery_report_{}".format(event_type))

def _handle_cancelled_report(data):
    message_id = data.get("id") or data.get("messageId") or data.get("message_id")
    if message_id:
        frappe.db.set_value("SMS Queue", {"gateway_message_id": message_id}, "status", "Cancelled")
        frappe.db.set_value("SMS Log", {"gateway_message_id": message_id}, "status", "Cancelled")
        frappe.db.commit()

def _handle_app_started(data):
    """App booted on a phone — refresh the matching SMS Device heartbeat/SIM info.

    Payload (Android SMS Gateway `app:started`): ``{ deviceId, simCards: [{
    slotIndex, simNumber, phoneNumber, carrierName, iccid }] }``.
    """
    device_id = data.get("deviceId") or data.get("device_id") or ""
    sim_cards = data.get("simCards") or data.get("sim_cards") or []
    if not device_id or not isinstance(sim_cards, list):
        return
    devices = frappe.get_all("SMS Device", filters={"device_id": device_id}, pluck="name")
    for device_name in devices:
        updates = {"is_online": 1, "last_heartbeat": now()}
        sim_number = cint(frappe.db.get_value("SMS Device", device_name, "sim_number") or 0)
        selected = None
        for sim in sim_cards:
            if not isinstance(sim, dict):
                continue
            if not sim_number:
                selected = selected or sim
                continue
            if cint(sim.get("simNumber") or sim.get("sim_number") or 0) == sim_number:
                selected = sim
                break
        if selected:
            if selected.get("phoneNumber"):
                updates["sim_phone_number"] = selected["phoneNumber"]
            if selected.get("carrierName"):
                updates["carrier_name"] = selected["carrierName"]
        frappe.db.set_value("SMS Device", device_name, updates)
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

def _format_mms_message(data, text):
    """Build a human-readable message body from an MMS webhook payload."""
    parts = []
    if text:
        parts.append(text)
    subject = data.get("subject")
    if subject and subject != text:
        parts.append("[Subject: {}]".format(subject))
    attachments = data.get("attachments") or []
    if attachments:
        names = [
            a.get("name") or a.get("contentType") or "attachment"
            for a in attachments if isinstance(a, dict)
        ]
        parts.append("[{} attachment(s): {}]".format(len(names), ", ".join(names)))
    size = data.get("size")
    if size:
        parts.append("[Size: {} bytes]".format(size))
    return "\n".join(parts) if parts else "[MMS]"

def _handle_incoming_sms(data, event_type="sms:received"):
    phone = data.get("sender") or data.get("phone") or data.get("from") or data.get("phoneNumber") or ""
    message = (
        data.get("message")
        or data.get("text")
        or data.get("body")
        or data.get("subject")
        or data.get("data")
        or ""
    )
    profile_name = data.get("profileName") or data.get("contact_name") or ""
    device_id = data.get("deviceId") or data.get("device_id") or ""
    sim_number = data.get("simNumber") or data.get("sim_number") or 0
    received_at = data.get("receivedAt") or data.get("received_at") or now()

    if event_type in ("mms:received", "mms:downloaded"):
        message = _format_mms_message(data, message)
    elif event_type == "sms:data-received":
        message = message or "[Data SMS]"

    if not phone or not message:
        return

    if _is_duplicate_webhook(data, "incoming"):
        return

    from sms_relay.utils.contact_manager import create_communication
    message_doc = {"message": message, "phone": phone, "received_at": received_at}
    create_communication(message_doc, phone, profile_name)

    queue = frappe.new_doc("SMS Queue")
    queue.recipient = phone
    queue.message = message
    queue.status = "Received"
    queue.sim_number = cint(sim_number) if sim_number else 0
    queue.insert(ignore_permissions=True)

    frappe.db.commit()

    _mark_webhook_seen(data, "incoming")

def _is_duplicate_webhook(data, prefix):
    cache_key = "webhook_{}_{}".format(prefix, hash(json.dumps(data, sort_keys=True)))
    return bool(frappe.cache().get_value(cache_key))

def _mark_webhook_seen(data, prefix):
    # TTL must outlive the full signature freshness window (max_age 900s plus
    # 60s future skew) so a replayed webhook can't pass signature checks after
    # the marker expires.
    cache_key = "webhook_{}_{}".format(prefix, hash(json.dumps(data, sort_keys=True)))
    frappe.cache().set_value(cache_key, True, expires_in_sec=900 + 60)
