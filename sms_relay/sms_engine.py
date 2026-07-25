"""Core SMS engine for the sms_relay Frappe app.

This module is the central hub for all outbound SMS operations. It integrates
with Frappe's ``send_sms`` hook so that every SMS dispatched through the
framework is routed through this relay engine instead of the default provider.

Architecture & Data Flow
------------------------
The primary entry point is :func:`send_sms`, which is invoked by
``frappe.sendmail`` / SMS Settings whenever an SMS needs to be sent. The
lifecycle of a single message follows this path::

    send_sms()
      → _clean_phone()          # Normalize phone to E.164
      → _check_opt_out()        # Skip opted-out recipients
      → _enqueue_sms()          # Persist to SMS Queue for async dispatch
        ↓ (background worker)
        → _select_device()      # Pick best device (priority, health, quota)
        → _send_to_device()     # HTTP POST to device gateway
        → _log_sms()            # Record outcome in SMS Log

Key responsibilities handled by this module:

* **Device selection** – picks the optimal gateway device based on priority,
  heartbeat freshness, daily quota, and per-device rate limiting.
* **Phone normalisation** – strips non-digit characters and applies country
  code defaults to produce valid E.164 numbers.
* **Opt-out checking** – queries the ``SMS Opt Out`` DocType to honour
  recipient preferences.
* **Rate limiting** – per-device throttle using Frappe's cache with a sliding
  60-second window.
* **Template rendering** – Jinja-based SMS templates via the ``SMS Template``
  DocType.
* **Queue management** – messages are persisted to ``SMS Queue`` for reliable
  async delivery with retry support.
* **Logging** – every sent/failed message is recorded in ``SMS Log`` for audit
  and troubleshooting.

Constants
---------
MAX_RETRIES : int
    Default maximum retry attempts per message.
RATE_LIMIT : int
    Default per-device messages per minute.
DEFAULT_TTL : int
    Default time-to-live in seconds for cached values.
"""

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
    """Process an outbound SMS request for a list of recipients.

    This is the primary entry point registered as Frappe's ``send_sms`` hook.
    For each recipient the phone number is cleaned, opt-out status is checked,
    and a queue entry is created for asynchronous delivery.  Invalid or
    opted-out numbers are silently skipped (with logging).

    Args:
        receiver_list (list[str]): List of raw phone number strings to send to.
        msg (str): The SMS message body.
        sender_name (str, optional): Identifier of the sender.  Currently unused
            by the relay engine but accepted for API compatibility.  Defaults
            to ``""``.
        success_msg (bool, optional): When ``True``, display a confirmation
            message to the Frappe user after queuing.  Defaults to ``True``.

    Returns:
        None
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
    """Drop-in replacement for Frappe's built-in ``send_sms`` function.

    Accepts either a comma-separated string or a list of recipients and
    delegates to :func:`send_sms`.  This function is used to monkey-patch
    the original Frappe SMS dispatcher so all messages flow through the
    relay engine.

    Args:
        recipient (str | list[str]): A comma-separated phone string or a
            list of phone number strings.
        message (str): The SMS message body.
        sender (str, optional): Sender identifier for API compatibility.
            Defaults to ``""``.

    Returns:
        dict: A status dict with keys ``"status"`` (always ``"queued"``) and
            ``"recipients"`` (int – number of recipients queued).
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
    """Load and cache the SMS Gateway Settings singleton as a plain dict.

    Reads the ``SMS Gateway Settings`` DocType, converts it to a dictionary
    of commonly used fields, and caches the result in Frappe's cache for
    120 seconds to avoid repeated DB lookups within the same request.

    Returns:
        dict: Configuration dictionary containing gateway URL, API keys,
            feature flags, templates, rate limits, and retry settings.
            Returns an empty dict ``{}`` if the settings DocType cannot
            be read.
    """
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
    """Select the best available SMS device for sending a message.

    Iterates through enabled ``SMS Device`` records ordered by priority
    (ascending) and applies three filters before selecting a device:

    1. **Quota** – skips devices whose ``sent_today`` has reached
       ``daily_quota``.
    2. **Heartbeat** – skips devices whose ``last_heartbeat`` is older
       than 5 minutes, indicating they may be offline.
    3. **Throttle** – skips devices that have hit the per-minute rate
       limit (see :func:`_throttle_check`).

    Args:
        recipient (str): The destination phone number (used for future
            routing logic; currently informational only).

    Returns:
        dict | None: A dictionary with device fields (``name``,
            ``device_name``, ``priority``, ``sim_slot``, ``sent_today``,
            ``daily_quota``, ``last_heartbeat``, ``gateway_url``) if a
            suitable device is found, otherwise ``None``.
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
    """Send an SMS message by POSTing to a device's HTTP gateway.

    Constructs a JSON payload with the destination phone, message body,
    SIM slot, and device name, then sends it to the device's ``/send``
    endpoint.  An ``X-API-Key`` header is included when an API key is
    configured in the gateway settings.

    Args:
        device (dict): Device dictionary returned by :func:`_select_device`.
            Must contain at least ``gateway_url`` and ``sim_slot``.
        phone (str): E.164-formatted destination phone number.
        message (str): The SMS message body to send.

    Returns:
        str: The ``message_id`` assigned by the device gateway, or an
            empty string if the response did not include one.

    Raises:
        ValueError: If no gateway URL is configured for the device.
        requests.exceptions.HTTPError: If the gateway returns a non-2xx
            status code (via ``response.raise_for_status()``).
        requests.exceptions.RequestException: On network errors or
            timeouts (30-second limit).
    """
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
    """Normalize a phone number to E.164 format.

    Strips non-digit characters (except ``+``), then applies the following
    logic:

    * If the result already starts with ``+``, it is assumed to be E.164
      and is returned as-is.
    * If a global ``country_code`` default is set in Frappe, it is
      prepended for local numbers.
    * As a fallback, numbers with 10 or more digits are assumed to be
      international and receive a leading ``+``.

    Args:
        phone (str | None): Raw phone number string (e.g. ``"0712345678"``,
            ``"+967712345678"``, ``"(071) 234-5678"``).

    Returns:
        str: E.164-formatted phone number (e.g. ``"+967712345678"``), or
            an empty string ``""`` if the input is ``None``, empty, or
            contains no digits.
    """
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
    """Resolve the primary mobile phone number for a Customer.

    Attempts two strategies in order:

    1. **Contact chain** – joins ``tabContact`` with ``tabDynamic Link``
       to find contacts linked to the Customer, preferring the primary
       contact.
    2. **Customer field fallback** – reads ``mobile_no`` or ``phone``
       directly from the ``Customer`` DocType.

    The resulting number is always passed through :func:`_clean_phone`
    before being returned.

    Args:
        customer_name (str | None): The name (ID) of the ``Customer``
            document, or ``None``/empty to skip lookup.

    Returns:
        str: E.164-formatted phone number, or an empty string ``""`` if
            no phone number could be resolved.
    """
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
    """Persist an ``SMS Log`` record for audit and troubleshooting.

    Creates and inserts an ``SMS Log`` document with all relevant metadata
    about the message, including the device used, reference document, and
    any error information.  The database is committed immediately after
    insertion.

    Args:
        phone (str): E.164-formatted destination phone number.
        message (str): The SMS message body that was (or was to be) sent.
        status (str): Outcome status, e.g. ``"Sent"``, ``"Failed"``,
            ``"Queued"``.
        device (str | None): Name of the ``SMS Device`` used, or ``None``.
        doctype (str | None): Frappe DocType name for the reference
            document, or ``None``.
        docname (str | None): Document name (ID) of the reference
            document, or ``None``.
        message_id (str | None): Gateway-assigned message identifier, or
            ``None``.
        error (str | None): Error description if the send failed, or
            ``None``.

    Returns:
        None

    Note:
        Failures during log creation are caught and written to Frappe's
        error log; they never propagate to the caller.
    """
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
    """Create an ``SMS Queue`` entry for asynchronous delivery.

    Persists the message to the queue DocType so that a background worker
    can pick it up, select a device, and send it.  The database is
    committed immediately after insertion.

    Args:
        phone (str): E.164-formatted destination phone number.
        message (str): The SMS message body.
        recipient_name (str | None): Human-readable name of the recipient,
            or ``None``.
        doctype (str | None): Frappe DocType name for the reference
            document, or ``None``.
        docname (str | None): Document name (ID) of the reference
            document, or ``None``.
        priority (int, optional): Queue priority; lower values are
            dispatched first.  Defaults to ``1``.
        template (str | None): Name of the ``SMS Template`` used to
            render the message, or ``None`` if a plain-text message.

    Returns:
        None

    Note:
        If ``phone`` is empty or falsy, the function returns immediately
        without creating a queue entry.  Failures during insertion are
        caught and written to Frappe's error log.
    """
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
    """Determine whether a phone number has opted out of SMS.

    Normalizes the phone number via :func:`_clean_phone` and then queries
    the ``SMS Opt Out`` DocType for a matching record with
    ``opted_out = 1``.

    Args:
        phone (str): Phone number to check (raw or E.164; it will be
            normalized internally).

    Returns:
        bool: ``True`` if the number has opted out, ``False`` otherwise
            (including when the normalized number is empty or no record
            exists).
    """
    normalized = _clean_phone(phone)
    if not normalized:
        return False

    exists = frappe.db.exists(
        "SMS Opt Out",
        {"phone": normalized, "opted_out": 1},
    )
    return bool(exists)


def _throttle_check(device_name):
    """Check whether a device has exceeded the per-minute rate limit.

    Uses Frappe's cache as a sliding-window counter.  Each call increments
    the counter for the given device; the counter resets after 60 seconds.

    Args:
        device_name (str): The ``name`` field of the ``SMS Device``
            document.

    Returns:
        bool: ``True`` if the device is throttled (count >= limit),
            ``False`` if the message is allowed through.
    """
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
    """Render an SMS message body from a named Jinja template.

    Loads the ``SMS Template`` DocType by name, extracts the ``body``
    (or ``message``) field, and renders it through Frappe's Jinja
    template engine with the supplied context variables.

    Args:
        template_name (str | None): Name of the ``SMS Template``
            document to render, or ``None``/empty to skip rendering.
        context (dict): Template variables to inject, e.g.
            ``{"customer_name": "John", "invoice_id": "INV-0001"}``.

    Returns:
        str: The rendered and stripped message body, or an empty string
            ``""`` if the template name is empty, the template is not
            found, or the template body is blank.  If rendering fails,
            the raw unrendered body is returned as a fallback.
    """
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
