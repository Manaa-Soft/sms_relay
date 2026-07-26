import frappe
from frappe import _
from frappe.utils import now, cint, add_to_date, getdate
from sms_relay.core.sms_utils import get_relay_settings

def process_sms_queue():
    pending = frappe.get_all(
        "SMS Queue",
        filters={"status": "Queued"},
        order_by="creation asc",
        limit=50,
        fields=["name"],
    )
    if not pending:
        return
    for item in pending:
        try:
            _process_queue_item(item.name)
        except Exception:
            frappe.log_error(title="SMS Queue Processing: {}".format(item.name))
    frappe.db.commit()

def _process_queue_item(queue_name):
    queue = frappe.get_doc("SMS Queue", queue_name)
    if queue.status != "Queued":
        return
    max_retries = cint(queue.max_retries) or 3
    if cint(queue.get("retry_count", 0)) >= max_retries:
        queue.status = "Failed"
        queue.save(ignore_permissions=True)
        return
    from sms_relay.core.sms_engine import _select_device, _send_to_device, _throttle_check, clean_phone
    phone = clean_phone(queue.recipient)
    if not phone:
        queue.status = "Failed"
        queue.save(ignore_permissions=True)
        return
    device_name = queue.device or _select_device(phone)
    if not device_name:
        queue.status = "Queued"
        queue.save(ignore_permissions=True)
        return
    if not _throttle_check(device_name):
        return
    result = _send_to_device(device_name, phone, queue.message)
    if result.get("success"):
        queue.status = "Sent"
        queue.save(ignore_permissions=True)
        from sms_relay.core.sms_engine import _log_sms
        _log_sms(phone, queue.message, "Sent", device_name=device_name, gateway_message_id=result.get("message_id"))
    else:
        retry_count = cint(queue.get("retry_count", 0)) + 1
        queue.retry_count = retry_count
        if retry_count >= max_retries:
            queue.status = "Failed"
        else:
            queue.status = "Queued"
            queue.next_retry_at = add_to_date(now(), minutes=2 ** retry_count)
        queue.save(ignore_permissions=True)

def process_outbox():
    pending = frappe.get_all(
        "SMS Outbox",
        filters={"status": ["in", ["Pending", "Failed"]], "next_retry_at": ["<=", now()]},
        order_by="next_retry_at asc",
        limit=20,
        fields=["name"],
    )
    for item in pending:
        try:
            _process_outbox_item(item.name)
        except Exception:
            frappe.log_error(title="SMS Outbox Processing: {}".format(item.name))
    frappe.db.commit()

def _process_outbox_item(outbox_name):
    outbox = frappe.get_doc("SMS Outbox", outbox_name)
    if outbox.status == "Sent":
        return
    if cint(outbox.attempts) >= cint(outbox.max_attempts):
        outbox.status = "Failed"
        outbox.save(ignore_permissions=True)
        return
    queue = frappe.get_doc("SMS Queue", outbox.sms_queue)
    if queue.status != "Queued":
        outbox.status = "Failed"
        outbox.save(ignore_permissions=True)
        return
    from sms_relay.core.sms_engine import _send_to_device, _throttle_check, clean_phone
    phone = clean_phone(queue.recipient)
    device_name = outbox.account
    if not device_name or not _throttle_check(device_name):
        outbox.attempts = cint(outbox.attempts) + 1
        outbox.next_retry_at = add_to_date(now(), minutes=2 ** cint(outbox.attempts))
        outbox.save(ignore_permissions=True)
        return
    result = _send_to_device(device_name, phone, queue.message)
    outbox.attempts = cint(outbox.attempts) + 1
    outbox.last_retry_at = now()
    if result.get("success"):
        outbox.status = "Sent"
        queue.status = "Sent"
        queue.save(ignore_permissions=True)
        from sms_relay.core.sms_engine import _log_sms
        _log_sms(phone, queue.message, "Sent", device_name=device_name, gateway_message_id=result.get("message_id"))
    else:
        outbox.error_message = result.get("error", "")
        if cint(outbox.attempts) >= cint(outbox.max_attempts):
            outbox.status = "Failed"
            queue.status = "Failed"
            queue.save(ignore_permissions=True)
        else:
            outbox.status = "Pending"
            outbox.next_retry_at = add_to_date(now(), minutes=2 ** cint(outbox.attempts))
    outbox.save(ignore_permissions=True)

def check_device_health():
    devices = frappe.get_all(
        "SMS Device",
        filters={"is_active": 1},
        fields=["name", "server_url", "gateway_type"],
    )
    for device in devices:
        try:
            _check_single_device(device)
        except Exception:
            frappe.log_error(title="Device Health Check: {}".format(device.name))

def _check_single_device(device):
    import requests
    if device.gateway_type == "Android SMS Gateway":
        base_url = (device.server_url or "").rstrip("/")
        url = "{}/api/mobile/v1/device".format(base_url)
        try:
            device_doc = frappe.get_doc("SMS Device", device.name)
            username = device_doc.username or ""
            password = device_doc.get_password("password") or ""
            auth = requests.auth.HTTPBasicAuth(username, password) if username else None
            settings = get_relay_settings()
            timeout = cint(settings.get("timeout")) or 10
            resp = requests.get(url, auth=auth, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                frappe.db.set_value("SMS Device", device.name, {
                    "is_active": 1,
                    "battery_level": data.get("batteryLevel"),
                    "signal_strength": data.get("signalStrength"),
                })
            else:
                frappe.db.set_value("SMS Device", device.name, "is_active", 0)
        except Exception:
            frappe.db.set_value("SMS Device", device.name, "is_active", 0)
        frappe.db.commit()

def send_overdue_reminders():
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "outstanding_amount": [">", 0],
            "due_date": ["<", getdate()],
        },
        fields=["name", "customer", "due_date", "outstanding_amount"],
        limit=50,
    )
    if not invoices:
        return
    for inv in invoices:
        try:
            from sms_relay.core.sms_engine import _get_customer_phone, _enqueue_sms
            phone = _get_customer_phone(inv.customer)
            if not phone:
                continue
            msg = "Dear {} - Reminder: Invoice {} of {} is overdue (due {}). Outstanding: {}. Please pay soon.".format(
                inv.customer, inv.name, frappe.utils.fmt_money(inv.outstanding_amount),
                frappe.utils.formatdate(inv.due_date),
            )
            _enqueue_sms(phone=phone, message=msg, priority="Normal")
        except Exception:
            frappe.log_error(title="Overdue SMS: {}".format(inv.name))

def retry_failed_sms():
    failed = frappe.get_all(
        "SMS Queue",
        filters={"status": "Failed"},
        fields=["name", "retry_count", "max_retries"],
        limit=50,
    )
    retried = 0
    for item in failed:
        if cint(item.retry_count) < cint(item.max_retries):
            frappe.db.set_value("SMS Queue", item.name, {
                "status": "Queued",
                "retry_count": cint(item.retry_count) + 1,
            })
            retried += 1
    frappe.db.commit()
    return {"retried": retried}

def cleanup_old_logs():
    retention_days = 90
    cutoff = add_to_date(getdate(), days=-retention_days)
    deleted = frappe.db.delete(
        "SMS Log",
        {"creation": ["<", cutoff]},
    )
    frappe.db.commit()
    return {"cleaned_up": deleted}

def reset_daily_quotas():
    devices = frappe.get_all("SMS Device", filters={"is_active": 1}, fields=["name"])
    for device in devices:
        frappe.db.set_value("SMS Device", device.name, "sent_today", 0)
    frappe.db.commit()

def process_bulk_messages():
    active_bulks = frappe.get_all(
        "SMS Bulk Message",
        filters={"status": ["in", ["Draft", "Processing"]]},
        fields=["name"],
    )
    for bulk in active_bulks:
        try:
            from sms_relay.core.bulk_engine import process_bulk_job
            process_bulk_job(bulk.name)
        except Exception:
            frappe.log_error(title="Bulk SMS Processing: {}".format(bulk.name))
