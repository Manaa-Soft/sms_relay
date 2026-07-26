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
    return result


@frappe.whitelist()
def send_sms_now(recipient=None, message=None, template=None, device=None, sim=None):
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
    from sms_relay.core.sms_engine import send_sms
    send_sms(phone_list, message, sender="")
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
