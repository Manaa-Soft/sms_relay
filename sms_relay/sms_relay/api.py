import frappe
from frappe import _
from frappe.utils import cint

from sms_relay.sms_engine import (
    _clean_phone,
    _select_device,
    _send_to_device,
    _log_sms,
    _enqueue_sms,
    _check_opt_out,
    _get_gateway_config,
    _render_template,
)


@frappe.whitelist()
def send_sms_now(recipient, message, template=None, device=None, sim=None):
    """Send an SMS immediately, bypassing the queue.

    Args:
        recipient: Phone number string.
        message: SMS body text.
        template: Optional SMS Template name to render.
        device: Optional device name to force a specific device.
        sim: Optional SIM slot number.

    Returns:
        dict with status, message_id, device.
    """
    phone = _clean_phone(recipient)
    if not phone:
        frappe.throw(_("Invalid phone number: {0}").format(recipient))

    if _check_opt_out(phone):
        frappe.throw(_("Phone number {0} has opted out of SMS").format(phone))

    if template:
        message = _render_template(template, {"phone": phone})
        if not message:
            frappe.throw(_("Template rendered to empty message"))

    if not message:
        frappe.throw(_("Message is required"))

    # Select or force a device
    if device:
        try:
            dev = frappe.get_doc("SMS Device", device)
            device_info = {
                "name": dev.name,
                "device_name": dev.device_name,
                "sim_slot": sim or dev.sim_slot or 1,
                "gateway_url": getattr(dev, "gateway_url", ""),
            }
        except frappe.DoesNotExistError:
            frappe.throw(_("Device {0} not found").format(device))
    else:
        device_info = _select_device(phone)
        if not device_info:
            frappe.throw(_("No available SMS device"))

    message_id = _send_to_device(device_info, phone, message)

    _log_sms(
        phone=phone,
        message=message,
        status="Sent",
        device=device_info.get("name"),
        message_id=message_id,
    )

    frappe.db.commit()

    return {
        "status": "sent",
        "message_id": message_id,
        "device": device_info.get("name"),
        "phone": phone,
    }


@frappe.whitelist()
def send_bulk_sms(recipients_csv, message, template=None):
    """Enqueue SMS for multiple recipients from a CSV string.

    Args:
        recipients_csv: Comma/newline-separated list of phone numbers.
        message: SMS body text.
        template: Optional SMS Template name.

    Returns:
        dict with queued count and list of invalid numbers.
    """
    if not message and not template:
        frappe.throw(_("Message or template is required"))

    if template:
        rendered = _render_template(template, {})
        if not rendered:
            frappe.throw(_("Template rendered to empty message"))

    numbers = []
    for line in str(recipients_csv).replace(";", ",").split("\n"):
        for part in line.split(","):
            cleaned = _clean_phone(part.strip())
            if cleaned:
                numbers.append(cleaned)

    # Deduplicate while preserving order
    seen = set()
    unique_numbers = []
    for num in numbers:
        if num not in seen:
            seen.add(num)
            unique_numbers.append(num)

    queued = 0
    skipped = []
    for phone in unique_numbers:
        if _check_opt_out(phone):
            skipped.append(phone)
            continue

        _enqueue_sms(
            phone=phone,
            message=message or f"Template: {template}",
            recipient_name="",
            doctype="",
            docname="",
            priority=1,
            template=template,
        )
        queued += 1

    frappe.db.commit()

    return {
        "status": "queued",
        "queued": queued,
        "skipped_opt_out": len(skipped),
        "invalid": len(numbers) - len(unique_numbers),
    }


@frappe.whitelist()
def get_device_health():
    """Return health status of all SMS devices.

    Returns:
        list of dicts with device info, online status, quota, heartbeat.
    """
    devices = frappe.get_all(
        "SMS Device",
        filters={"enabled": 1},
        fields=["name", "device_name", "status", "priority", "sim_slot",
                "sent_today", "daily_quota", "last_heartbeat", "gateway_url"],
        order_by="priority asc",
    )

    result = []
    for dev in devices:
        is_online = True
        if dev.last_heartbeat:
            try:
                from frappe.utils import time_diff_in_seconds, now_datetime
                diff = time_diff_in_seconds(now_datetime(), dev.last_heartbeat)
                is_online = diff < 300
            except Exception:
                is_online = False

        result.append({
            "device": dev.name,
            "device_name": dev.device_name,
            "online": is_online,
            "status": "Online" if is_online else "Offline",
            "priority": dev.priority,
            "sim_slot": dev.sim_slot,
            "sent_today": cint(dev.sent_today),
            "daily_quota": cint(dev.daily_quota),
            "quota_remaining": cint(dev.daily_quota) - cint(dev.sent_today),
            "last_heartbeat": str(dev.last_heartbeat) if dev.last_heartbeat else None,
        })

    return result


@frappe.whitelist()
def preview_template(template_name, doc_type=None, doc_name=None):
    """Render an SMS template with optional real document data.

    Args:
        template_name: SMS Template name.
        doc_type: Optional DocType to pull context from.
        doc_name: Optional document name.

    Returns:
        dict with rendered message and context used.
    """
    context = {}

    if doc_type and doc_name:
        try:
            doc = frappe.get_doc(doc_type, doc_name)
            context = {
                "doc": doc,
                "docname": doc.name,
            }
            # Inject common fields
            for field in ("customer", "supplier", "party", "grand_total",
                          "outstanding_amount", "posting_date", "due_date",
                          "company", "currency", "name"):
                if hasattr(doc, field):
                    context[field] = getattr(doc, field)

            from frappe.utils import fmt_money, getdate
            if "grand_total" in context and context.get("currency"):
                context["grand_total_formatted"] = fmt_money(
                    context["grand_total"], currency=context["currency"]
                )
            if "outstanding_amount" in context and context.get("currency"):
                context["outstanding_formatted"] = fmt_money(
                    context["outstanding_amount"], currency=context["currency"]
                )
            if hasattr(doc, "posting_date") and doc.posting_date:
                context["posting_date_formatted"] = getdate(doc.posting_date).strftime("%d-%m-%Y")
            if hasattr(doc, "due_date") and doc.due_date:
                context["due_date_formatted"] = getdate(doc.due_date).strftime("%d-%m-%Y")
        except Exception as e:
            frappe.throw(_("Could not load document: {0}").format(str(e)))

    rendered = _render_template(template_name, context)
    return {
        "template": template_name,
        "rendered": rendered,
        "context_keys": list(context.keys()),
    }


@frappe.whitelist()
def retry_sms(queue_name):
    """Manually retry a failed SMS Queue entry.

    Args:
        queue_name: SMS Queue document name.

    Returns:
        dict with updated status.
    """
    try:
        entry = frappe.get_doc("SMS Queue", queue_name)
    except frappe.DoesNotExistError:
        frappe.throw(_("SMS Queue entry {0} not found").format(queue_name))

    if entry.status not in ("Failed", "Sent"):
        frappe.throw(_("Only Failed or Sent entries can be retried"))

    frappe.db.set(
        "SMS Queue", queue_name,
        {
            "status": "Queued",
            "retry_count": 0,
            "error": None,
        },
        update_modified=True,
    )
    frappe.db.commit()

    return {"status": "requeued", "name": queue_name}


@frappe.whitelist()
def get_sms_stats():
    """Return today's SMS statistics.

    Returns:
        dict with sent, failed, pending, delivered counts.
    """
    from frappe.utils import nowdate

    today = nowdate()

    stats = frappe.db.sql(
        """SELECT status, COUNT(*) as count
           FROM `tabSMS Log`
           WHERE DATE(creation) = %s
           GROUP BY status""",
        (today,),
        as_dict=True,
    )

    result = {"sent": 0, "failed": 0, "pending": 0, "delivered": 0}
    for row in stats:
        status_key = (row.status or "").lower()
        if status_key in result:
            result[status_key] = cint(row.count)

    result["total"] = sum(result.values())
    result["date"] = today

    return result
