"""Self-registration of SMS Relay webhooks on gateway devices.

The gateway app stores webhooks server-side (private/cloud mode) and syncs them
to the phone. SMS Relay can therefore provision every event it understands via
``POST /webhooks`` and reconcile stale registrations, replacing the manual
"add webhook" step in the app.
"""

import json

import frappe
from sms_relay.gateway.client import GatewayClient, GATEWAY_WEBHOOK_EVENTS


def get_webhook_url(device=None):
    """Public URL that the gateway should POST webhooks to.

    Resolution order: ``SMS Device.webhook_callback_url``, then
    ``SMS Gateway Settings.webhook_url``, then the auto-detected site URL for
    ``sms_relay.api.webhook_receiver.incoming_webhook``.
    """
    settings = frappe.get_single("SMS Gateway Settings")
    url = ""
    if device:
        url = device.get("webhook_callback_url") or ""
    if not url:
        url = settings.get("webhook_url") or ""
    if not url:
        url = frappe.utils.get_url("/api/method/sms_relay.api.webhook_receiver.incoming_webhook")
    return url.rstrip("/")


def _load_registrations(device):
    raw = device.get("webhook_registrations") or ""
    if not raw:
        return {}
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(items, list):
        return {}
    return {item.get("event"): item for item in items if isinstance(item, dict) and item.get("event")}


def _save_registrations(device, registrations):
    if not registrations:
        return
    device.webhook_registrations = json.dumps(registrations)
    device.save(ignore_permissions=True)
    frappe.db.commit()


def provision_webhooks(device, events=None):
    """Register every gateway event on the device (idempotent).

    Returns ``{"status": "ok", "webhooks": [{event, id, url}]}``.
    """
    client = GatewayClient(device)
    url = get_webhook_url(device)
    device_id = device.device_id or None
    events = list(events) if events else list(GATEWAY_WEBHOOK_EVENTS)

    existing = client.list_webhooks()
    existing_map = {}
    for item in existing:
        if not isinstance(item, dict):
            continue
        key = (item.get("event"), (item.get("url") or "").rstrip("/"))
        existing_map[key] = item.get("id")

    registrations = []
    for event in events:
        key = (event, url)
        webhook_id = existing_map.get(key)
        if not webhook_id:
            data = client.create_webhook(event, url, device_id=device_id)
            if data and data.get("id"):
                webhook_id = data["id"]
        if webhook_id:
            registrations.append({"event": event, "id": webhook_id, "url": url})

    _save_registrations(device, registrations)
    return {"status": "ok", "webhooks": registrations}


def reconcile_webhooks(device):
    """Delete gateway webhooks that SMS Relay does not want and register
    missing ones. Returns the same shape as :func:`provision_webhooks`."""
    client = GatewayClient(device)
    url = get_webhook_url(device)
    wanted = set(GATEWAY_WEBHOOK_EVENTS)

    existing = client.list_webhooks()
    for item in existing:
        if not isinstance(item, dict):
            continue
        if item.get("event") in wanted and (item.get("url") or "").rstrip("/") == url:
            continue
        if item.get("id"):
            client.delete_webhook(item["id"])

    return provision_webhooks(device, events=list(wanted))
