import csv
import io
import json
import requests
import frappe
from frappe import _
from frappe.utils import now, cint
from sms_relay.core.sms_utils import clean_phone, count_sms_parts, get_relay_settings


def _get_gateway_auth(settings, device=None):
    """Resolve auth for the Android SMS Gateway server.

    The Docker server uses Basic Auth with device credentials.
    """
    headers = {"Content-Type": "application/json"}
    auth = None
    if device:
        username = device.username or ""
        password = device.get_password("password") or ""
        if username:
            auth = requests.auth.HTTPBasicAuth(username, password)
    return headers, auth


@frappe.whitelist()
def test_connection(device_name=None):
    settings = get_relay_settings()
    timeout = cint(settings.get("timeout")) or 10
    device = frappe.get_doc("SMS Device", device_name) if device_name else None
    gateway_url = (device.server_url if device else settings.get("gateway_url") or "").rstrip("/")
    if not gateway_url:
        return {"success": False, "error": "No gateway URL configured"}
    headers, auth = _get_gateway_auth(settings, device)
    url = "{}/api/mobile/v1/device".format(gateway_url)
    try:
        resp = requests.get(url, headers=headers, auth=auth, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            return {"success": True, "device": data}
        return {"success": False, "error": "HTTP {}: {}".format(resp.status_code, resp.text[:200])}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)[:200]}


@frappe.whitelist()
def connect_device(device_name=None):
    if not device_name:
        frappe.throw(_("Device name is required"))
    device = frappe.get_doc("SMS Device", device_name)
    base_url = (device.server_url or "").rstrip("/")
    if not base_url:
        return {"success": False, "error": "No server URL configured"}
    settings = get_relay_settings()
    headers, auth = _get_gateway_auth(settings, device)
    updates = {"is_online": 0, "last_heartbeat": now()}
    result = {"success": False}

    try:
        resp = requests.get(
            "{}/api/mobile/v1/device".format(base_url),
            headers=headers, auth=auth, timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            updates["is_online"] = 1
            updates["last_heartbeat"] = now()
            if data.get("id"):
                updates["device_id"] = data["id"]
            if data.get("name"):
                updates["device_model"] = data["name"]
            sim_cards = data.get("simCards") or []
            if sim_cards:
                sim = sim_cards[0]
                if sim.get("carrierName"):
                    updates["carrier_name"] = sim["carrierName"]
                if sim.get("phoneNumber"):
                    updates["sim_phone_number"] = sim["phoneNumber"]
                if sim.get("simNumber"):
                    updates["sim_number"] = sim["simNumber"]
            result["device"] = data
    except requests.exceptions.RequestException as e:
        result["error"] = str(e)[:200]

    try:
        resp = requests.get("{}/health".format(base_url), timeout=10)
        if resp.status_code == 200:
            health = resp.json()
            checks = health.get("checks") or {}
            battery = checks.get("battery:level") or {}
            if battery.get("observedValue") is not None:
                updates["battery_level"] = battery["observedValue"]
            signal = checks.get("connection:status") or {}
            if signal.get("observedValue") is not None:
                updates["signal_strength"] = "Connected" if signal["observedValue"] else "Disconnected"
            if health.get("version"):
                updates["app_version"] = health["version"]
            result["health"] = health
    except requests.exceptions.RequestException:
        pass

    frappe.db.set_value("SMS Device", device_name, updates)
    frappe.db.commit()
    result["success"] = updates.get("is_online", 0) == 1
    result["updates"] = updates

    # Self-register webhooks so no manual app-side setup is required.
    try:
        from sms_relay.gateway.webhooks import provision_webhooks
        result["webhooks"] = provision_webhooks(device).get("webhooks", [])
    except Exception:
        result["webhooks"] = []
    return result


@frappe.whitelist()
def send_sms_now(recipient=None, message=None, template=None, device=None, sim=None,
                 message_id=None, ttl_seconds=None, valid_until=None, schedule_at=None,
                 data_payload=None, data_port=None):
    if not recipient:
        frappe.throw(_("Recipient is required"))
    if not message and not template:
        frappe.throw(_("Message or Template is required"))
    if isinstance(recipient, str):
        recipient = [recipient]
    phone_list = []
    for r in recipient:
        phone_list.append(clean_phone(r))
    phone_list = [p for p in phone_list if p]
    if not phone_list:
        frappe.throw(_("No valid phone numbers provided"))
    if template:
        from sms_relay.core.sms_engine import _render_template
        message = _render_template(template, {"recipient_list": phone_list})
    if not message:
        frappe.throw(_("Message cannot be empty"))

    # Idempotency check
    if message_id:
        existing = frappe.db.exists("SMS Log", {"message_id": message_id, "status": "Sent"})
        if existing:
            return {"status": "already_sent", "recipients": phone_list, "message_id": message_id}

    from sms_relay.core.sms_engine import send_sms
    send_sms(phone_list, message, sender="", message_id=message_id,
             ttl_seconds=ttl_seconds, valid_until=valid_until, schedule_at=schedule_at,
             data_payload=data_payload, data_port=data_port)
    return {"status": "sent", "recipients": phone_list, "message_length": len(message)}


@frappe.whitelist()
def send_bulk_sms(recipients_csv=None, recipients_json=None, message=None, template=None, account=None, scheduled_at=None):
    if not recipients_csv and not recipients_json:
        frappe.throw(_("Recipients are required (CSV or JSON)"))
    if not message and not template:
        frappe.throw(_("Message or Template is required"))
    from sms_relay.core.bulk_engine import create_bulk_job
    bulk = create_bulk_job(
        message_type="Text" if message else "Template",
        message=message,
        template=template,
        recipients_csv=recipients_csv,
        account=account,
        scheduled_at=scheduled_at,
    )
    return {"status": "created", "bulk_job": bulk.name, "total_recipients": bulk.total_recipients}


@frappe.whitelist()
def get_device_health():
    devices = frappe.get_all(
        "SMS Device",
        filters={"is_active": 1},
        fields=["name", "device_name", "is_active", "battery_level", "signal_strength",
                "hourly_quota", "daily_quota", "gateway_type", "sim_slot"],
    )
    result = []
    for device in devices:
        sent_today = frappe.db.count(
            "SMS Log",
            filters={
                "device": device.name,
                "status": "Sent",
                "creation": [">=", frappe.utils.getdate()],
            },
        )
        sent_hour = frappe.db.count(
            "SMS Log",
            filters={
                "device": device.name,
                "status": "Sent",
                "creation": [">=", frappe.utils.add_to_date(now(), hours=-1)],
            },
        )
        result.append({
            "name": device.name,
            "device_name": device.device_name,
            "is_active": device.is_active,
            "battery_level": device.battery_level,
            "signal_strength": device.signal_strength,
            "sim_slot": device.sim_slot,
            "gateway_type": device.gateway_type,
            "sent_today": sent_today,
            "daily_quota": device.daily_quota,
            "sent_this_hour": sent_hour,
            "hourly_quota": device.hourly_quota,
            "quota_usage_today": "{:.1f}%".format((sent_today / max(device.daily_quota, 1)) * 100),
        })
    return result


@frappe.whitelist()
def preview_template(template_name=None, doc_type=None, doc_name=None, message_text=None):
    if message_text:
        return {
            "message": message_text,
            "sms_info": count_sms_parts(message_text),
        }
    if not template_name:
        frappe.throw(_("Template name is required"))
    context = {}
    if doc_type and doc_name:
        doc = frappe.get_doc(doc_type, doc_name)
        context["doc"] = doc
    context["frappe"] = frappe
    from sms_relay.core.sms_engine import _render_template
    rendered = _render_template(template_name, context)
    return {
        "message": rendered,
        "sms_info": count_sms_parts(rendered),
    }


@frappe.whitelist()
def retry_sms(queue_name=None):
    if not queue_name:
        frappe.throw(_("Queue name is required"))
    queue = frappe.get_doc("SMS Queue", queue_name)
    if queue.status not in ("Failed", "Queued"):
        frappe.throw(_("Only failed or queued messages can be retried"))
    queue.status = "Queued"
    queue.save(ignore_permissions=True)
    frappe.db.commit()
    return {"status": "requeued", "name": queue.name}


@frappe.whitelist()
def get_sms_stats():
    today = frappe.utils.getdate()
    stats = {
        "sent_today": frappe.db.count("SMS Log", filters={"status": "Sent", "creation": [">=", today]}),
        "failed_today": frappe.db.count("SMS Log", filters={"status": "Failed", "creation": [">=", today]}),
        "delivered_today": frappe.db.count("SMS Log", filters={"delivery_status": "Delivered", "creation": [">=", today]}),
        "queued": frappe.db.count("SMS Queue", filters={"status": "Queued"}),
        "total_devices": frappe.db.count("SMS Device", filters={"is_active": 1}),
        "active_devices": frappe.db.count("SMS Device", filters={"is_active": 1}),
        "opted_out_count": frappe.db.count("SMS Opt Out", filters={"opted_out": 1}),
    }
    return stats


@frappe.whitelist()
def get_notification_preview(notification_name=None, doc_type=None, doc_name=None):
    if not notification_name:
        frappe.throw(_("Notification name is required"))
    notification = frappe.get_doc("SMS Notification", notification_name)
    context = {}
    if doc_type and doc_name:
        doc = frappe.get_doc(doc_type, doc_name)
        context["doc"] = doc
    context["frappe"] = frappe
    from jinja2 import Template
    rendered = ""
    if notification.message_template:
        tmpl = Template(notification.message_template)
        rendered = tmpl.render(**context)
    return {
        "notification": notification.name,
        "reference_doctype": notification.reference_doctype,
        "event": notification.event,
        "message": rendered,
        "sms_info": count_sms_parts(rendered) if rendered else None,
    }


@frappe.whitelist()
def cancel_message(queue_name=None):
    """Cancel a queued SMS message before it is sent."""
    if not queue_name:
        frappe.throw(_("Queue name is required"))
    from sms_relay.core.sms_engine import cancel_message as _cancel
    return _cancel(queue_name)


@frappe.whitelist()
def get_message_history(from_date=None, to_date=None, status=None, device=None, phone=None, limit=50, offset=0):
    """Get SMS message history with filtering."""
    filters = []
    if from_date:
        filters.append(["creation", ">=", from_date])
    if to_date:
        filters.append(["creation", "<=", to_date])
    if status:
        filters.append(["status", "=", status])
    if device:
        filters.append(["device", "=", device])
    if phone:
        filters.append(["phone", "like", "%{}%".format(phone)])

    logs = frappe.get_all(
        "SMS Log",
        filters=filters,
        fields=["name", "phone", "recipient_name", "message", "status", "delivery_status",
                "device", "device_id", "gateway_message_id", "message_id",
                "queued_at", "sent_at", "delivered_at", "error_message", "creation"],
        order_by="creation desc",
        limit=cint(limit),
        start=cint(offset),
    )
    total = frappe.db.count("SMS Log", filters=filters)
    return {"messages": logs, "total": total, "limit": cint(limit), "offset": cint(offset)}


@frappe.whitelist()
def get_inbox(from_date=None, to_date=None, phone=None, limit=50, offset=0):
    """Get incoming SMS messages with filtering."""
    filters = [["status", "=", "Received"]]
    if from_date:
        filters.append(["creation", ">=", from_date])
    if to_date:
        filters.append(["creation", "<=", to_date])
    if phone:
        filters.append(["recipient", "like", "%{}%".format(phone)])

    messages = frappe.get_all(
        "SMS Queue",
        filters=filters,
        fields=["name", "recipient", "message", "status", "creation",
                "reference_doctype", "reference_name"],
        order_by="creation desc",
        limit=cint(limit),
        start=cint(offset),
    )
    total = frappe.db.count("SMS Queue", filters=filters)
    return {"messages": messages, "total": total, "limit": cint(limit), "offset": cint(offset)}


@frappe.whitelist()
def get_device_settings(device_name=None):
    """Get device settings from the gateway."""
    if not device_name:
        frappe.throw(_("Device name is required"))
    device = frappe.get_doc("SMS Device", device_name)
    base_url = (device.server_url or "").rstrip("/")
    if not base_url:
        return {"success": False, "error": "No server URL configured"}
    settings = get_relay_settings()
    headers, auth = _get_gateway_auth(settings, device)
    try:
        resp = requests.get(
            "{}/api/mobile/v1/settings".format(base_url),
            headers=headers, auth=auth, timeout=15,
        )
        if resp.status_code == 200:
            return {"success": True, "settings": resp.json()}
        return {"success": False, "error": "HTTP {}: {}".format(resp.status_code, resp.text[:200])}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)[:200]}


@frappe.whitelist()
def update_device_settings(device_name=None, settings_json=None):
    """Update device settings on the gateway."""
    if not device_name:
        frappe.throw(_("Device name is required"))
    if not settings_json:
        frappe.throw(_("Settings JSON is required"))
    device = frappe.get_doc("SMS Device", device_name)
    base_url = (device.server_url or "").rstrip("/")
    if not base_url:
        return {"success": False, "error": "No server URL configured"}
    settings = get_relay_settings()
    headers, auth = _get_gateway_auth(settings, device)
    if isinstance(settings_json, str):
        try:
            settings_json = json.loads(settings_json)
        except (ValueError, TypeError):
            return {"success": False, "error": "Invalid JSON"}
    try:
        resp = requests.put(
            "{}/api/mobile/v1/settings".format(base_url),
            json=settings_json,
            headers=headers, auth=auth, timeout=15,
        )
        if resp.status_code in (200, 204):
            return {"success": True}
        return {"success": False, "error": "HTTP {}: {}".format(resp.status_code, resp.text[:200])}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)[:200]}


@frappe.whitelist()
def get_structured_health():
    """Get structured health check results for all devices."""
    devices = frappe.get_all(
        "SMS Device",
        filters={"is_active": 1},
        fields=["name", "device_name", "is_active", "is_online", "battery_level",
                "signal_strength", "carrier_name", "device_model", "app_version",
                "sim_phone_number", "hourly_quota", "daily_quota"],
    )
    checks = []
    for device in devices:
        sent_today = frappe.db.count(
            "SMS Log",
            filters={"device": device.name, "status": "Sent", "creation": [">=", frappe.utils.getdate()]},
        )
        failed_today = frappe.db.count(
            "SMS Log",
            filters={"device": device.name, "status": "Failed", "creation": [">=", frappe.utils.getdate()]},
        )
        status = "pass"
        if not device.is_online:
            status = "fail"
        elif device.battery_level is not None and device.battery_level < 20:
            status = "warn"
        elif failed_today > sent_today and sent_today > 0:
            status = "warn"

        checks.append({
            "name": device.name,
            "device_name": device.device_name,
            "status": status,
            "is_online": device.is_online,
            "battery_level": device.battery_level,
            "signal_strength": device.signal_strength,
            "carrier_name": device.carrier_name,
            "device_model": device.device_model,
            "app_version": device.app_version,
            "sent_today": sent_today,
            "failed_today": failed_today,
            "failure_rate": "{:.1f}%".format((failed_today / max(sent_today + failed_today, 1)) * 100),
            "quota_usage": "{:.1f}%".format((sent_today / max(device.daily_quota, 1)) * 100),
        })

    overall_status = "pass"
    for check in checks:
        if check["status"] == "fail":
            overall_status = "fail"
            break
        if check["status"] == "warn":
            overall_status = "warn"

    return {
        "status": overall_status,
        "checks": checks,
        "total_devices": len(checks),
        "online_devices": sum(1 for c in checks if c["is_online"]),
    }


@frappe.whitelist()
def register_device_webhooks(device_name=None, reconcile=0):
    """Provision (or reconcile) every gateway webhook event for a device."""
    if not device_name:
        frappe.throw(_("Device name is required"))
    device = frappe.get_doc("SMS Device", device_name)
    from sms_relay.gateway.webhooks import provision_webhooks, reconcile_webhooks
    if cint(reconcile):
        return reconcile_webhooks(device)
    return provision_webhooks(device)


@frappe.whitelist()
def get_webhook_registrations(device_name=None):
    """Return the webhook registrations stored for a device."""
    if not device_name:
        frappe.throw(_("Device name is required"))
    device = frappe.get_doc("SMS Device", device_name)
    import json as _json
    raw = device.get("webhook_registrations") or ""
    try:
        return _json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []


@frappe.whitelist()
def refresh_device_inbox(device_name=None, limit=100):
    """Ask the device to rescan its inbox and import messages into SMS Queue."""
    if not device_name:
        frappe.throw(_("Device name is required"))
    device = frappe.get_doc("SMS Device", device_name)
    from sms_relay.gateway.inbox import refresh_device_inbox as _refresh
    return _refresh(device, limit=cint(limit))


@frappe.whitelist()
def get_message_status(device_name=None, gateway_message_id=None):
    """Fetch the gateway's current state for a sent message."""
    if not device_name:
        frappe.throw(_("Device name is required"))
    if not gateway_message_id:
        frappe.throw(_("Gateway message ID is required"))
    device = frappe.get_doc("SMS Device", device_name)
    from sms_relay.gateway.status import get_message_status as _get_status
    data = _get_status(device, gateway_message_id)
    if not data:
        return {"success": False, "error": "No status returned by the gateway"}
    return {"success": True, "message": data}


@frappe.whitelist()
def get_device_logs(device_name=None, limit=100):
    """Fetch recent logs from the gateway server for a device."""
    if not device_name:
        frappe.throw(_("Device name is required"))
    device = frappe.get_doc("SMS Device", device_name)
    from sms_relay.gateway.client import GatewayClient
    client = GatewayClient(device)
    return {"success": True, "logs": client.get_logs(limit=cint(limit))}
