import hashlib
import hmac
import json
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import cint

from sms_relay.sms_engine import _get_gateway_config, MAX_RETRIES


@frappe.whitelist(allow_guest=True)
def incoming_webhook():
    """Handle incoming webhook callbacks from SMS gateway devices.

    Expects JSON payload with fields:
        - event: "sms:delivered" | "sms:failed" | "sms:sent" | "system:ping"
        - message_id: str (for sms events)
        - device_name: str
        - phone: str (optional)
        - error: str (optional, for sms:failed)
        - timestamp: str (optional)
        - signature: str (optional HMAC)
    """
    config = _get_gateway_config()

    # Parse payload
    try:
        if frappe.request.data:
            if isinstance(frappe.request.data, bytes):
                payload = json.loads(frappe.request.data.decode("utf-8"))
            else:
                payload = json.loads(frappe.request.data)
        else:
            payload = frappe.form_dict
    except (json.JSONDecodeError, ValueError):
        frappe.response.http_status_code = 400
        return {"status": "error", "message": "Invalid JSON payload"}

    if not payload:
        frappe.response.http_status_code = 400
        return {"status": "error", "message": "Empty payload"}

    # Validate HMAC signature if configured
    webhook_secret = config.get("webhook_secret")
    if webhook_secret:
        signature = payload.get("signature", "")
        if not _verify_signature(payload, signature, webhook_secret):
            frappe.log_error("SMS Relay: webhook signature verification failed")
            frappe.response.http_status_code = 403
            return {"status": "error", "message": "Invalid signature"}

    event = payload.get("event", "")
    message_id = payload.get("message_id", "")
    device_name = payload.get("device_name", "")
    error_msg = payload.get("error", "")

    if event == "sms:delivered":
        _handle_delivered(message_id, device_name)
    elif event == "sms:failed":
        _handle_failed(message_id, device_name, error_msg)
    elif event == "sms:sent":
        _handle_sent(message_id, device_name)
    elif event == "system:ping":
        _handle_heartbeat(device_name)
    else:
        frappe.log_error(f"SMS Relay: unknown webhook event '{event}'")
        frappe.response.http_status_code = 400
        return {"status": "error", "message": f"Unknown event: {event}"}

    frappe.db.commit()
    frappe.response.http_status_code = 200
    return {"status": "ok"}


def _verify_signature(payload, signature, secret):
    """Verify HMAC-SHA256 signature of the webhook payload."""
    if not signature or not secret:
        return False

    try:
        signable = json.dumps(
            {k: v for k, v in payload.items() if k != "signature"},
            sort_keys=True,
            separators=(",", ":"),
        )
        expected = hmac.new(
            secret.encode("utf-8"),
            signable.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


def _handle_delivered(message_id, device_name):
    """Update queue and log status to Delivered."""
    if not message_id:
        return

    queue = frappe.get_all(
        "SMS Queue",
        filters={"message_id": message_id},
        fields=["name", "status"],
    )
    for entry in queue:
        frappe.db.set("SMS Queue", entry.name, "status", "Delivered", update_modified=True)

    frappe.db.sql(
        """UPDATE `tabSMS Log`
           SET status = 'Delivered'
           WHERE message_id = %s AND status != 'Delivered'""",
        (message_id,),
    )


def _handle_failed(message_id, device_name, error_msg):
    """Update queue and log status to Failed with error details."""
    if not message_id:
        return

    error_text = error_msg[:500] if error_msg else "Delivery failed"
    config = _get_gateway_config()
    max_retries = cint(config.get("max_retry_count")) or MAX_RETRIES

    queue = frappe.get_all(
        "SMS Queue",
        filters={"message_id": message_id},
        fields=["name", "status", "retry_count"],
    )
    for entry in queue:
        retry_count = cint(entry.get("retry_count", 0)) + 1
        new_status = "Queued" if retry_count < max_retries else "Failed"
        frappe.db.set(
            "SMS Queue", entry.name,
            {
                "status": new_status,
                "retry_count": retry_count,
                "error": error_text,
            },
            update_modified=True,
        )

    frappe.db.sql(
        """UPDATE `tabSMS Log`
           SET status = 'Failed', error = %s
           WHERE message_id = %s""",
        (error_text, message_id),
    )


def _handle_sent(message_id, device_name):
    """Confirm an SMS was accepted by the carrier (sent from device)."""
    if not message_id:
        return

    queue = frappe.get_all(
        "SMS Queue",
        filters={"message_id": message_id, "status": ["in", ["Sending", "Queued"]]},
        fields=["name"],
    )
    for entry in queue:
        frappe.db.set("SMS Queue", entry.name, "status", "Sent", update_modified=True)

    frappe.db.sql(
        """UPDATE `tabSMS Log`
           SET status = 'Sent'
           WHERE message_id = %s AND status IN ('Sending', 'Queued')""",
        (message_id,),
    )


def _handle_heartbeat(device_name):
    """Update the device's last_heartbeat timestamp."""
    if not device_name:
        return

    try:
        frappe.db.set(
            "SMS Device", device_name,
            {
                "last_heartbeat": datetime.now(),
                "status": "Online",
            },
            update_modified=True,
        )
    except Exception:
        frappe.log_error(f"SMS Relay: heartbeat update failed for device '{device_name}'")
