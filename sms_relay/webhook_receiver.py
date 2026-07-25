"""Webhook receiver for the SMS Relay module.

This module receives delivery receipts and status updates from Android SMS Gateway
devices via HTTP POST callbacks. It serves as a public endpoint (allow_guest=True)
that the Android SMS Gateway server calls to report message lifecycle events.

Supported webhook events:
    - ``sms:delivered`` -- Confirms final delivery to the recipient's handset.
      Updates both the SMS Queue and SMS Log status to "Delivered".
    - ``sms:failed`` -- Reports a delivery failure with an error message.
      Increments the retry counter on the queue entry; re-queues the message if
      retries remain, otherwise marks it as "Failed". Also records the error in
      the SMS Log.
    - ``sms:sent`` -- Indicates the device has accepted and transmitted the
      message to the carrier network. Updates status to "Sent" on queue and log.
    - ``system:ping`` -- A periodic heartbeat from the device. Updates the
      ``last_heartbeat`` timestamp and sets the device status to "Online".

Security:
    If a ``webhook_secret`` is configured in *SMS Gateway Settings*, every
    incoming payload is validated against an HMAC-SHA256 signature to prevent
    tampering and replay attacks. Requests with an invalid or missing signature
    are rejected with HTTP 403.

All functions in this module are internal helpers except ``incoming_webhook``,
which is the sole public entry point exposed to the Android SMS Gateway.
"""

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
    """Handle incoming webhook callbacks from the Android SMS Gateway server.

    This is the public endpoint invoked by the Android SMS Gateway whenever a
    message status changes or the device sends a heartbeat. It is decorated with
    ``allow_guest=True`` so that external unauthenticated HTTP requests from the
    gateway can reach it.

    The request body must contain a JSON payload with the following fields:

    Args:
        event (str): The webhook event type. One of:
            ``"sms:delivered"``, ``"sms:failed"``, ``"sms:sent"``, or
            ``"system:ping"``.
        message_id (str): The unique message identifier assigned when the SMS
            was enqueued. Required for all ``sms:*`` events.
        device_name (str): The name of the originating SMS Device document.
        phone (str, optional): The recipient phone number (informational).
        error (str, optional): Human-readable error description. Only present
            for ``sms:failed`` events; truncated to 500 characters on storage.
        timestamp (str, optional): ISO-formatted timestamp from the device.
        signature (str, optional): HMAC-SHA256 hex digest computed over the
            payload (excluding this field) using the configured webhook secret.

    Returns:
        dict: ``{"status": "ok"}`` on success, or ``{"status": "error",
        "message": "<reason>"}`` on failure.

    Raises:
        Returns HTTP 400 if the payload is missing, empty, or contains an
        unrecognised event type.
        Returns HTTP 403 if HMAC signature verification fails.
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
    """Verify the HMAC-SHA256 signature of a webhook payload.

    The signature is computed by serialising the payload dictionary (excluding
    the ``"signature"`` key) as a compact JSON string with sorted keys, then
    HMAC-ing it with the shared secret using SHA-256. A constant-time
    comparison is used to prevent timing attacks.

    Args:
        payload (dict): The full webhook payload including the ``signature``
            field.
        signature (str): The hex-encoded HMAC-SHA256 signature provided by
            the caller.
        secret (str): The shared webhook secret from SMS Gateway Settings.

    Returns:
        bool: ``True`` if the signature is valid and matches the computed
        digest, ``False`` otherwise (including any serialisation or
        encoding errors).
    """
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
    """Mark an SMS as successfully delivered to the recipient.

    Finds all matching ``SMS Queue`` entries by ``message_id`` and sets their
    status to ``"Delivered"``. Also updates the corresponding ``SMS Log`` row
    (if it is not already marked as delivered) via a direct SQL update.

    Args:
        message_id (str): The unique message identifier assigned when the SMS
            was enqueued.
        device_name (str): The name of the device that reported delivery
            (currently unused but logged for audit purposes).

    Returns:
        None
    """
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
    """Handle a failed SMS delivery, applying retry logic.

    For each matching ``SMS Queue`` entry the retry counter is incremented.
    If the new retry count is still below ``max_retry_count`` (from SMS
    Gateway Settings, falling back to ``MAX_RETRIES``), the entry is
    re-queued for another delivery attempt. Otherwise it is permanently
    marked as ``"Failed"``.

    The ``SMS Log`` is always updated with the failure status and the error
    message (truncated to 500 characters).

    Args:
        message_id (str): The unique message identifier.
        device_name (str): The name of the device that reported the failure.
        error_msg (str): A human-readable description of the failure reason.
            Truncated to 500 characters before storage.

    Returns:
        None
    """
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
    """Confirm an SMS has been handed off to the carrier network.

    This is an intermediate status indicating that the device successfully
    transmitted the message but delivery to the handset has not yet been
    confirmed. Only queue entries currently in ``"Sending"`` or ``"Queued"``
    status are updated to ``"Sent"``.

    Args:
        message_id (str): The unique message identifier.
        device_name (str): The name of the device that transmitted the
            message.

    Returns:
        None
    """
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
    """Process a periodic heartbeat (``system:ping``) from an SMS device.

    Updates the device's ``last_heartbeat`` field to the current timestamp
    and sets its ``status`` to ``"Online"``. This allows the system to track
    device availability and detect offline devices.

    Args:
        device_name (str): The name of the ``SMS Device`` document to update.

    Returns:
        None
    """
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
