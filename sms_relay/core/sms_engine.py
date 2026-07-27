import json
import frappe
import requests
from frappe import _
from frappe.utils import now, cint, getdate
from sms_relay.core.sms_utils import (
    clean_phone,
    get_relay_settings,
    is_opted_out,
    count_sms_parts,
    validate_phone_list,
)

def send_sms(receiver_list, msg, sender="", message_id=None, ttl_seconds=None, valid_until=None, schedule_at=None, **kwargs):
    settings = get_relay_settings()
    if not sender:
        sender = settings.get("sender_name") or ""

    for receiver in receiver_list:
        phone = clean_phone(receiver)
        if not phone:
            continue
        if is_opted_out(phone):
            _log_sms(phone, msg, "Cancelled", error="Number is opted out")
            continue
        device = _select_device(phone)
        if not device:
            _log_sms(phone, msg, "Failed", error="No SMS device available")
            continue
        if not _throttle_check(device):
            _log_sms(phone, msg, "Failed", error="Rate limit exceeded for device {}".format(device))
            continue
        result = _send_to_device(device, phone, msg, sender)
        if result.get("success"):
            _log_sms(phone, msg, "Sent", device_name=device, gateway_message_id=result.get("message_id"), message_id=message_id)
        else:
            _enqueue_sms(phone, msg, device, priority="Normal", message_id=message_id,
                         ttl_seconds=ttl_seconds, valid_until=valid_until, scheduled_at=schedule_at)

def send_sms_override(recipient, message, sender=None, **kwargs):
    if isinstance(recipient, str):
        recipient = [recipient]
    send_sms(recipient, message, sender=sender or "")
    return {"recipients": recipient, "message": message}

def _select_device(recipient):
    settings = get_relay_settings()
    strategy = settings.get("routing_strategy") or "Round Robin"
    devices = frappe.get_all(
        "SMS Device",
        filters={"is_active": 1},
        fields=["name", "device_name", "priority", "hourly_quota", "daily_quota"],
        order_by="priority asc",
    )
    if not devices:
        return None
    if strategy == "Priority":
        return _select_device_priority(devices, recipient)
    elif strategy == "Random":
        import random
        return random.choice(devices).name
    else:
        return _select_device_round_robin(devices, recipient)

def _select_device_priority(devices, recipient):
    settings = get_relay_settings()
    failover = settings.get("failover_enabled", 1)
    for device in devices:
        quota_ok = _check_quota(device)
        if quota_ok:
            return device.name
    if failover:
        for device in devices:
            return device.name
    return None

def _select_device_round_robin(devices, recipient):
    counter = cint(frappe.cache().get_value("sms_round_robin_counter") or 0)
    idx = counter % len(devices)
    frappe.cache().set_value("sms_round_robin_counter", counter + 1)
    device = devices[idx]
    if _check_quota(device):
        return device.name
    for i in range(len(devices)):
        alt_idx = (idx + i + 1) % len(devices)
        if _check_quota(devices[alt_idx]):
            return devices[alt_idx].name
    return devices[0].name

def _check_quota(device):
    device_doc = frappe.get_doc("SMS Device", device.name)
    sent_today = frappe.db.count(
        "SMS Log",
        filters={
            "device": device.name,
            "status": "Sent",
            "creation": [">=", getdate()],
        },
    )
    daily_quota = cint(device_doc.daily_quota) or 5000
    if sent_today >= daily_quota:
        return False
    return True

def _throttle_check(device_name):
    settings = get_relay_settings()
    global_limit = cint(settings.get("global_rate_limit")) or 60
    recent_count = frappe.db.count(
        "SMS Log",
        filters={
            "device": device_name,
            "status": "Sent",
            "creation": [">=", frappe.utils.add_to_date(now(), minutes=-1)],
        },
    )
    return recent_count < global_limit

def _send_to_device(device_name, phone, message, sender="", queue_doc=None):
    device = frappe.get_doc("SMS Device", device_name)
    if device.gateway_type == "Android SMS Gateway":
        result = _send_android_gateway(device, phone, message, sender, queue_doc=queue_doc)
    else:
        result = _send_custom_http(device, phone, message, sender)

    # Send interval delay
    if result.get("success"):
        settings = get_relay_settings()
        min_delay = cint(settings.get("send_interval_min")) or 0
        max_delay = cint(settings.get("send_interval_max")) or 0
        if min_delay > 0 or max_delay > 0:
            import time, random
            delay = random.uniform(min_delay, max_delay)
            time.sleep(delay)

    return result

def _send_android_gateway(device, phone, message, sender, queue_doc=None):
    # Idempotency: skip if message_id already sent
    if queue_doc and queue_doc.message_id:
        existing = frappe.db.exists("SMS Log", {
            "message_id": queue_doc.message_id,
            "status": "Sent"
        })
        if existing:
            return {"success": True, "message_id": queue_doc.message_id}

    base_url = (device.server_url or "").rstrip("/")
    if not base_url:
        return {"success": False, "error": "No server URL configured on device"}
    settings = get_relay_settings()
    api_path = (settings.get("api_path") or "/api/3rdparty/v1/message").lstrip("/")
    timeout = cint(settings.get("timeout")) or 30
    url = "{}/{}".format(base_url, api_path)
    payload = {
        "textMessage": {"text": message},
        "phoneNumbers": [phone],
        "simNumber": cint(device.sim_number) if device.sim_number else 1,
        "withDeliveryReport": True,
    }
    if device.device_id:
        payload["deviceId"] = device.device_id
    if queue_doc:
        priority_map = {"High": 100, "Normal": 0, "Low": -100}
        tier = queue_doc.priority_tier or "Normal"
        payload["priority"] = priority_map.get(tier, 0)

    username = device.username or ""
    password = device.get_password("password") or ""
    if not username:
        return {"success": False, "error": "No credentials: set username/password on SMS Device '{}'".format(device.name)}

    auth = requests.auth.HTTPBasicAuth(username, password)
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, auth=auth, timeout=timeout)
        if resp.status_code in (200, 201, 202):
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            return {"success": True, "message_id": data.get("id") or data.get("messageId") or data.get("requestId")}
        return {"success": False, "error": "HTTP {}: {}".format(resp.status_code, resp.text[:200])}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)[:200]}

def _send_custom_http(device, phone, message, sender):
    base_url = (device.server_url or "").rstrip("/")
    api_key = device.get_password("api_key") or ""
    headers = {"Authorization": "Bearer {}".format(api_key)} if api_key else {}
    headers["Content-Type"] = "application/json"
    payload = {"phone": phone, "message": message, "sender": sender}
    try:
        resp = requests.post(base_url, json=payload, headers=headers, timeout=30)
        if resp.status_code in (200, 201, 202):
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            return {"success": True, "message_id": data.get("id") or data.get("messageId")}
        return {"success": False, "error": "HTTP {}: {}".format(resp.status_code, resp.text[:200])}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)[:200]}

def _log_sms(phone, message, status, device_name=None, gateway_message_id=None, error=None, message_id=None, device_id=None):
    log = frappe.new_doc("SMS Log")
    log.phone = phone
    log.message = message
    log.status = status
    if device_name:
        log.device = device_name
    if device_id:
        log.device_id = device_id
    if message_id:
        log.message_id = message_id
    log.gateway_message_id = gateway_message_id
    if error:
        log.error_message = error
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log

def _enqueue_sms(phone, message, device_name=None, priority="Normal", channel="SMS", max_retries=3, message_id=None, ttl_seconds=None, valid_until=None, **kwargs):
    queue = frappe.new_doc("SMS Queue")
    queue.recipient = phone
    queue.message = message
    queue.status = "Queued"
    queue.priority_tier = priority
    queue.max_retries = max_retries
    if device_name:
        queue.device = device_name
    if message_id:
        queue.message_id = message_id
    if ttl_seconds:
        queue.ttl_seconds = ttl_seconds
    if valid_until:
        queue.valid_until = valid_until
    meta = frappe.get_meta("SMS Queue")
    for key, val in kwargs.items():
        if meta.get_field(key):
            queue.set(key, val)
    queue.insert(ignore_permissions=True)
    frappe.db.commit()
    return queue

def _get_customer_phone(customer):
    if not customer:
        return None
    phone = frappe.db.get_value("Customer", customer, "mobile_no") or frappe.db.get_value("Customer", customer, "phone")
    if phone:
        return clean_phone(phone)
    contact = frappe.db.get_value(
        "Dynamic Link",
        {"link_doctype": "Customer", "link_name": customer},
        "parent",
    )
    if contact:
        phone = frappe.db.get_value("Contact", contact, "mobile_no") or frappe.db.get_value("Contact", contact, "phone")
        if phone:
            return clean_phone(phone)
    return None

def _get_supplier_phone(supplier):
    if not supplier:
        return None
    phone = frappe.db.get_value("Supplier", supplier, "mobile_no") or frappe.db.get_value("Supplier", supplier, "phone")
    if phone:
        return clean_phone(phone)
    return None

def cancel_message(queue_name):
    """Cancel a queued SMS message before it is sent."""
    queue = frappe.get_doc("SMS Queue", queue_name)
    if queue.status not in ("Queued",):
        frappe.throw(_("Only queued messages can be cancelled"))
    from frappe.utils import now_datetime
    queue.status = "Cancelled"
    queue.cancelled_at = now_datetime()
    queue.save(ignore_permissions=True)
    frappe.db.commit()

    # Log the cancellation
    _log_sms(queue.recipient, queue.message, "Cancelled", device_name=queue.device)

    return {"status": "cancelled", "name": queue.name}

def _render_template(template_name, context):
    template = frappe.get_doc("SMS Template", template_name)
    body = template.message_template or template.template or ""
    if not body:
        return ""
    from jinja2 import Template
    tmpl = Template(body)
    return tmpl.render(**context)
