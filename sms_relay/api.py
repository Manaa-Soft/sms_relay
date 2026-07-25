"""Public RPC API for the SMS Relay module.

This module exposes whitelisted methods that can be called via
``frappe.call()`` from client-side JavaScript, other Frappe/ERPNext apps, or
external integrations. Every public function is decorated with
``@frappe.whitelist()``, making it accessible over HTTP at
``/api/method/sms_relay.api.<function_name>``.

Provided methods:
    - ``send_sms_now``  -- Send a single SMS immediately, bypassing the queue.
    - ``send_bulk_sms`` -- Enqueue SMS messages for multiple recipients from a
      CSV-formatted string.
    - ``get_device_health`` -- Retrieve real-time health and quota information
      for all enabled SMS devices.
    - ``preview_template`` -- Render an SMS template with optional real
      document data for preview purposes.
    - ``retry_sms``     -- Manually re-queue a failed or sent SMS Queue entry
      for another delivery attempt.
    - ``get_sms_stats`` -- Return aggregate send/failed/pending/delivered
      statistics for the current day.

All methods rely on internal helpers from ``sms_relay.sms_engine`` for phone
number cleaning, device selection, HTTP delivery, logging, and opt-out checks.
"""

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
    """Send an SMS immediately, bypassing the background queue.

    The message is dispatched synchronously through the selected device's
    Android SMS Gateway HTTP endpoint. A log entry is written to ``SMS Log``
    before the function returns.

    Args:
        recipient (str): The recipient's phone number. Automatically cleaned
            and normalised by ``_clean_phone``. International prefixes are
            preserved.
        message (str): The SMS body text. Required when ``template`` is not
            provided.
        template (str, optional): The name of an ``SMS Template`` document to
            render instead of using the raw ``message``. The template is
            rendered with ``{"phone": phone}`` as context. If both ``message``
            and ``template`` are supplied, the rendered template output replaces
            ``message``.
        device (str, optional): The name of a specific ``SMS Device`` document
            to force delivery through. If omitted, the system automatically
            selects the best available device via ``_select_device``.
        sim (int, optional): The SIM slot number to use when a specific
            ``device`` is forced. Defaults to the device's own ``sim_slot``
            value or ``1``.

    Returns:
        dict: A dictionary containing:
            - ``status`` (str): ``"sent"`` on success.
            - ``message_id`` (str): The unique message identifier assigned by
              the gateway.
            - ``device`` (str): The name of the device that sent the message.
            - ``phone`` (str): The cleaned recipient phone number.

    Raises:
        frappe.ValidationError: If the phone number is invalid, the recipient
            has opted out, the template renders to an empty string, the message
            is empty, the specified device does not exist, or no devices are
            available.
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
    """Enqueue SMS messages for multiple recipients from a CSV-formatted string.

    Each phone number is cleaned, deduplicated, and checked against the opt-out
    list. Valid numbers are added to the ``SMS Queue`` via ``_enqueue_sms``
    for asynchronous delivery by the SMS engine worker.

    Args:
        recipients_csv (str): A comma- or newline-separated (or mixed) string
            of phone numbers. Semicolons are treated as commas.
        message (str): The SMS body text. Required when ``template`` is not
            provided.
        template (str, optional): The name of an ``SMS Template`` document. If
            provided, each queued entry records the template name so the SMS
            engine can render it with the appropriate document context at
            send time.

    Returns:
        dict: A dictionary containing:
            - ``status`` (str): ``"queued"``.
            - ``queued`` (int): Number of messages successfully enqueued.
            - ``skipped_opt_out`` (int): Number of recipients skipped because
              they opted out of SMS.
            - ``invalid`` (int): Number of entries removed during
              deduplication (duplicates).

    Raises:
        frappe.ValidationError: If neither ``message`` nor ``template`` is
            provided, or if the template renders to an empty string.
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
    """Return real-time health status of all enabled SMS devices.

    Queries every enabled ``SMS Device`` document and determines online
    status by checking whether the last heartbeat was received within the
    last 300 seconds (5 minutes). Quota information is computed by
    subtracting ``sent_today`` from ``daily_quota``.

    Returns:
        list[dict]: A list of dictionaries, one per enabled device, each
        containing:
            - ``device`` (str): Document name of the SMS Device.
            - ``device_name`` (str): Human-readable device name.
            - ``online`` (bool): ``True`` if a heartbeat was received within
              the last 5 minutes.
            - ``status`` (str): ``"Online"`` or ``"Offline"``.
            - ``priority`` (int): Device priority (lower = preferred).
            - ``sim_slot`` (int): Active SIM slot number.
            - ``sent_today`` (int): Number of SMS sent today.
            - ``daily_quota`` (int): Maximum SMS allowed per day.
            - ``quota_remaining`` (int): ``daily_quota - sent_today``.
            - ``last_heartbeat`` (str or None): ISO-formatted timestamp of
              the last heartbeat, or ``None`` if never received.

    Returns an empty list if no devices are enabled.
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
    """Render an SMS template with optional real document data for preview.

    Used by the UI to show a live preview of what the final SMS will look
    like. When ``doc_type`` and ``doc_name`` are both provided the referenced
    document is loaded and its common fields (customer, grand_total,
    outstanding_amount, posting_date, due_date, etc.) are injected into the
    template context along with formatted money and date strings.

    Args:
        template_name (str): The name of an ``SMS Template`` document.
        doc_type (str, optional): The DocType name of a document to use as
            template context (e.g. ``"Sales Invoice"``).
        doc_name (str, optional): The document name/ID to load. Must be
            supplied together with ``doc_type``.

    Returns:
        dict: A dictionary containing:
            - ``template`` (str): The template name.
            - ``rendered`` (str): The final rendered SMS body, or ``None`` if
              rendering failed.
            - ``context_keys`` (list[str]): The keys present in the template
              context (useful for debugging missing variables).

    Raises:
        frappe.ValidationError: If the document cannot be loaded from the
            given ``doc_type`` and ``doc_name``.
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
    """Manually re-queue a failed or sent SMS Queue entry for retry.

    Resets the entry's ``status`` to ``"Queued"``, clears the ``error``
    message, and resets ``retry_count`` to ``0`` so the SMS engine worker
    will pick it up on the next processing cycle.

    Args:
        queue_name (str): The document name of the ``SMS Queue`` entry to
            retry.

    Returns:
        dict: A dictionary containing:
            - ``status`` (str): ``"requeued"``.
            - ``name`` (str): The document name of the re-queued entry.

    Raises:
        frappe.ValidationError: If the ``SMS Queue`` entry does not exist, or
            if its current status is neither ``"Failed"`` nor ``"Sent"``.
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
    """Return aggregate SMS statistics for the current day.

    Queries the ``SMS Log`` table grouped by status for today's date and
    returns counts for each known status plus a total.

    Returns:
        dict: A dictionary containing:
            - ``sent`` (int): Messages successfully sent from the device.
            - ``failed`` (int): Messages that failed delivery.
            - ``pending`` (int): Messages still in the queue or being sent.
            - ``delivered`` (int): Messages confirmed delivered to handsets.
            - ``total`` (int): Sum of all the above counts.
            - ``date`` (str): The ``YYYY-MM-DD`` date these statistics cover.
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
