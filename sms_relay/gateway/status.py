"""Delivery-status reconciliation fallback.

Webhooks are the primary delivery-report channel. This module provides a
periodic sweep that asks the gateway for the current state of messages that were
sent but never received a terminal webhook (``GET /messages/{id}``).
"""

import frappe
from frappe.utils import add_to_date, cint, now

from sms_relay.gateway.client import GatewayClient, PROCESSING_STATE_MAP


def get_message_status(device, gateway_message_id):
    """Fetch the gateway's current state for a sent message, or None."""
    client = GatewayClient(device)
    return client.get_message_status(gateway_message_id)


def _apply_status(queue_name, gateway_message_id, status, state, data):
    """Update the matching SMS Queue and SMS Log rows.

    ``sms:sent``/status rows are keyed by ``gateway_message_id`` so a batched
    send (multiple recipients sharing one gateway id) updates every row.
    """
    fields = {"status": status}
    if state == "Delivered":
        fields["delivery_status"] = "Delivered"
        fields["sent_at"] = fields.get("sent_at") or now()
    frappe.db.set_value("SMS Queue", queue_name, fields)

    logs = frappe.get_all(
        "SMS Log",
        filters={"gateway_message_id": gateway_message_id},
        pluck="name",
    )
    for log_name in logs:
        log_fields = {
            "status": status,
            "delivery_status": status,
        }
        if state == "Delivered":
            log_fields["delivered_at"] = now()
        elif state == "Failed":
            recipient_errors = data.get("recipients") or []
            error = None
            for recipient in recipient_errors:
                if isinstance(recipient, dict) and recipient.get("error"):
                    error = recipient["error"]
                    break
            if error:
                log_fields["error_message"] = error
        frappe.db.set_value("SMS Log", log_name, log_fields)
    return True


def sync_delivery_status(age_minutes=30, limit=50):
    """Sweep recently-sent messages whose status never updated via webhook.

    Returns ``{"status": "ok", "updated": int}`` or ``{"status": "disabled"}``.
    """
    settings = frappe.get_single("SMS Gateway Settings")
    if not cint(settings.get("status_sync_enabled")):
        return {"status": "disabled", "updated": 0}

    age_minutes = cint(settings.get("status_sync_age_minutes")) or cint(age_minutes)
    cutoff = add_to_date(now(), minutes=-cint(age_minutes))

    candidates = frappe.get_all(
        "SMS Queue",
        filters={
            "status": "Sent",
            "gateway_message_id": ["is", "set"],
            "modified": ["<=", cutoff],
        },
        fields=["name", "device", "gateway_message_id"],
        order_by="modified asc",
        limit=cint(limit),
    )

    updated = 0
    for item in candidates:
        if not item.get("device"):
            continue
        device = frappe.get_doc("SMS Device", item["device"])
        if device.gateway_type != "Android SMS Gateway":
            continue
        data = get_message_status(device, item["gateway_message_id"])
        if not data or not isinstance(data, dict):
            continue
        state = data.get("state")
        status = PROCESSING_STATE_MAP.get(state)
        if not status:
            continue
        if _apply_status(item["name"], item["gateway_message_id"], status, state, data):
            updated += 1

    frappe.db.commit()
    return {"status": "ok", "updated": updated}
