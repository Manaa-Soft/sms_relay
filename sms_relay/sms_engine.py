import re
import hmac
import hashlib
import json
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import cint, cstr, nowdate

MAX_RETRIES = 3
RATE_LIMIT = 30
DEFAULT_TTL = 86400


def send_sms(receiver_list, msg, sender_name="", success_msg=True):
    """Frappe send_sms hook entry point.

    Called by frappe.sendmail / SMS Settings. Routes each recipient through
    the relay engine instead of the default provider.
    """
    if not receiver_list:
        return

    for phone in receiver_list:
        cleaned = _clean_phone(phone)
        if not cleaned:
            frappe.log_error(f"SMS Relay: invalid phone number '{phone}'")
            continue

        if _check_opt_out(cleaned):
            continue

        doctype = frappe.form_dict.get("doctype") or ""
        docname = frappe.form_dict.get("name") or ""

        _enqueue_sms(
            phone=cleaned,
            message=msg,
            recipient_name="",
            doctype=doctype,
            docname=docname,
            priority=1,
            template=None,
        )

    if success_msg:
        frappe.msgprint(_("SMS queued for {0} recipient(s)").format(len(receiver_list)))


def send_sms_override(recipient, message, sender=""):
    """Override for frappe.core.doctype.sms_settings.sms_settings.send_sms.

    Accepts the same signature as the original but routes through the relay.
    """
    receiver_list = []
    if isinstance(recipient, list):
        receiver_list = recipient
    elif isinstance(recipient, str):
        receiver_list = [r.strip() for r in recipient.split(",") if r.strip()]

    send_sms(receiver_list, msg=message, sender_name=sender, success_msg=False)
    return {"status": "queued", "recipients": len(receiver_list)}


# ---------------------------------------------------------------------------
# Gateway helpers
# ---------------------------------------------------------------------------

def _get_gateway_config():
    """Return SMS Gateway Settings singleton as a dict, with caching."""
    cache_key = "sms_relay_gateway_config"
    cached = frappe.cache().get_value(cache_key)
    if cached is not None:
        return cached

    try:
        settings = frappe.get_single("SMS Gateway Settings")
    except Exception:
        frappe.log_error("SMS Relay: unable to read SMS Gateway Settings")
        return {}

    config = {
        "enabled": cint(settings.get("enabled")),
        "gateway_url": (settings.get("gateway_url") or "").strip().rstrip("/"),
        "api_key": settings.get("api_key") or "",
        "api_secret": settings.get("api_secret") or "",
        "webhook_secret": settings.get("webhook_secret") or "",
        "default_sender": settings.get("default_sender") or "",
        "send_invoice_sms": cint(settings.get("send_invoice_sms")),
        "send_payment_sms": cint(settings.get("send_payment_sms")),
        "send_payment_request_sms": cint(settings.get("send_payment_request_sms")),
        "send_overdue_reminders": cint(settings.get("send_overdue_reminders")),
        "reminder_intervals": settings.get("reminder_intervals") or "7,14,30,60,90",
        "invoice_template": settings.get("invoice_template") or "",
        "payment_template": settings.get("payment_template") or "",
        "payment_request_template": settings.get("payment_request_template") or "",
        "overdue_template": settings.get("overdue_template") or "",
        "max_retry_count": cint(settings.get("max_retry_count")) or MAX_RETRIES,
        "rate_limit": cint(settings.get("rate_limit")) or RATE_LIMIT,
    }

    frappe.cache().set_value(cache_key, config, expires_in_sec=120)
    return config


def _select_device(recipient):
    """Pick the best SMS device based on priority, health, and quota.

    Returns a device dict or None.
    """
    devices = frappe.get_all(
        "SMS Device",
        filters={"enabled": 1, "status": "Online"},
        fields=["name", "device_name", "priority", "sim_slot", "sent_today",
                "daily_quota", "last_heartbeat", "gateway_url"],
        order_by="priority asc",
    )

    if not devices:
        frappe.log_error("SMS Relay: no enabled online devices available")
        return None

    now = datetime.now()
    best = None

    for dev in devices:
        # Skip if quota exhausted
        if dev.daily_quota and cint(dev.sent_today) >= cint(dev.daily_quota):
            continue

        # Skip if heartbeat stale (> 5 minutes)
        if dev.last_heartbeat:
            try:
                hb = frappe.utils.get_datetime(dev.last_heartbeat)
                if (now - hb).total_seconds() > 300:
                    continue
            except Exception:
                continue

        # Throttle check
        if _throttle_check(dev.name):
            continue

        best = dev
        break

    return best


def _send_to_device(device, phone, message):
    """POST an SMS to the device gateway. Returns message_id or raises."""
    import requests

    gateway_url = device.get("gateway_url") or _get_gateway_config().get("gateway_url", "")
    if not gateway_url:
        raise ValueError("No gateway URL configured for device")

    payload = {
        "phone": phone,
        "message": message,
        "sim": device.get("sim_slot", 1),
        "device_name": device.get("device_name", ""),
    }

    headers = {"Content-Type": "application/json"}
    api_key = _get_gateway_config().get("api_key")
    if api_key:
        headers["X-API-Key"] = api_key

    response = requests.post(
        gateway_url.rstrip("/") + "/send",
        json=payload,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    message_id = data.get("message_id") or data.get("id") or ""
    return message_id


# ---------------------------------------------------------------------------
# Phone utilities
# ---------------------------------------------------------------------------

def _clean_phone(phone):
    """Normalize a phone number to E.164 format."""
    if not phone:
        return ""

    digits = re.sub(r"[^\d+]", "", cstr(phone).strip())

    if not digits:
        return ""

    # Already E.164
    if digits.startswith("+"):
        return digits

    # Local numbers – try to prepend country from defaults
    default_country = frappe.defaults.get_global_default("country_code") or ""
    if default_country and not digits.startswith("+"):
        return f"+{default_country}{digits}"

    # Fallback: assume 10+ digit international without +
    if len(digits) >= 10:
        return f"+{digits}"

    return digits


def _get_customer_phone(customer_name):
    """Look up primary mobile phone for a Customer via Contact chain."""
    if not customer_name:
        return ""

    # Try dynamic link via Contact
    contacts = frappe.db.sql(
        """SELECT c.phone, c.mobile_no, c.name
           FROM `tabContact` c
           INNER JOIN `tabDynamic Link` dl
             ON dl.parent = c.name
             AND dl.link_doctype = 'Customer'
             AND dl.link_name = %s
           WHERE c.phone IS NOT NULL OR c.mobile_no IS NOT NULL
           ORDER BY c.is_primary_contact DESC
           LIMIT 1""",
        (customer_name,),
        as_dict=True,
    )

    if contacts:
        phone = contacts[0].get("mobile_no") or contacts[0].get("phone") or ""
        return _clean_phone(phone)

    # Fallback: Customer.doctype field
    try:
        customer = frappe.get_doc("Customer", customer_name)
        phone = getattr(customer, "mobile_no", None) or getattr(customer, "phone", None) or ""
        return _clean_phone(phone)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_sms(phone, message, status, device=None, doctype=None, docname=None,
             message_id=None, error=None):
    """Create an SMS Log entry."""
    try:
        log = frappe.get_doc({
            "doctype": "SMS Log",
            "phone": phone,
            "message": message,
            "status": status,
            "device": device,
            "reference_doctype": doctype,
            "reference_docname": docname,
            "message_id": message_id,
            "error": error,
            "sent_at": frappe.utils.now_datetime(),
        })
        log.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error("SMS Relay: failed to create SMS Log entry")


def _enqueue_sms(phone, message, recipient_name=None, doctype=None, docname=None,
                  priority=1, template=None):
    """Create an SMS Queue entry for async dispatch."""
    if not phone:
        return

    try:
        queue_entry = frappe.get_doc({
            "doctype": "SMS Queue",
            "phone": phone,
            "recipient_name": recipient_name or "",
            "message": message,
            "status": "Queued",
            "priority": priority,
            "reference_doctype": doctype,
            "reference_docname": docname,
            "template": template,
            "retry_count": 0,
        })
        queue_entry.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(f"SMS Relay: failed to enqueue SMS to {phone}")


# ---------------------------------------------------------------------------
# Opt-out & throttling
# ---------------------------------------------------------------------------

def _check_opt_out(phone):
    """Return True if the phone number has opted out of SMS."""
    normalized = _clean_phone(phone)
    if not normalized:
        return False

    exists = frappe.db.exists(
        "SMS Opt Out",
        {"phone": normalized, "opted_out": 1},
    )
    return bool(exists)


def _throttle_check(device_name):
    """Rate-limit per device using frappe.cache. Returns True if throttled."""
    config = _get_gateway_config()
    limit = cint(config.get("rate_limit")) or RATE_LIMIT

    cache_key = f"sms_relay_throttle:{device_name}"
    count = frappe.cache().get_value(cache_key) or 0

    if count >= limit:
        return True

    frappe.cache().set_value(cache_key, count + 1, expires_in_sec=60)
    return False


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def _render_template(template_name, context):
    """Render an SMS template with Jinja, injecting context data."""
    if not template_name:
        return ""

    try:
        template_doc = frappe.get_doc("SMS Template", template_name)
        body = template_doc.body or template_doc.get("message") or ""
    except Exception:
        frappe.log_error(f"SMS Relay: template '{template_name}' not found")
        return ""

    if not body:
        return ""

    try:
        rendered = frappe.render_template(body, context)
        return rendered.strip()
    except Exception:
        frappe.log_error(f"SMS Relay: template render error for '{template_name}'")
        return body
