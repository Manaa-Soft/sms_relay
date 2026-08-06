"""Backfill incoming SMS from the gateway inbox into SMS Relay.

Webhooks deliver new messages in real time; this module optionally pulls the
device's stored inbox (``GET /inbox``) so messages that arrived while the site
was unreachable are not lost. Deduplicated by the gateway inbox message id.
"""

import frappe
from frappe.utils import cint, now_datetime

from sms_relay.gateway.client import GatewayClient


def sync_device_inbox(device, since=None, limit=100):
    """Import the device's inbox into SMS Queue (status Received).

    Returns ``{"status": "ok", "created": int, "total": int}``.
    """
    client = GatewayClient(device)
    params = {"limit": cint(limit)}
    if since:
        params["since"] = since
    messages = client.list_inbox(**params)

    created = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        inbox_id = msg.get("id")
        sender = msg.get("sender") or msg.get("phoneNumber") or ""
        if not inbox_id or not sender:
            continue
        if frappe.db.exists("SMS Queue", {"inbox_message_id": inbox_id}):
            continue

        content = msg.get("contentPreview") or msg.get("message") or "[SMS]"
        sim_number = cint(msg.get("simNumber") or 0)
        received_at = msg.get("createdAt") or now_datetime()
        recipient = msg.get("recipient") or ""

        queue = frappe.new_doc("SMS Queue")
        queue.recipient = sender
        queue.message = content
        queue.status = "Received"
        queue.sim_number = sim_number
        queue.inbox_message_id = inbox_id
        if recipient:
            queue.reference_name = recipient
        queue.insert(ignore_permissions=True)
        created += 1

    frappe.db.commit()
    return {"status": "ok", "created": created, "total": len(messages)}


def refresh_device_inbox(device, since=None, limit=100):
    """Ask the device to rescan its inbox, then import it."""
    client = GatewayClient(device)
    client.refresh_inbox()
    return sync_device_inbox(device, since=since, limit=limit)
