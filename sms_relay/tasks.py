"""Scheduled and background tasks for the SMS Relay system.

This module contains all Frappe scheduler-driven tasks that power the SMS
gateway pipeline. Each function is intended to be registered as a scheduler
event (via hooks.py ``scheduler_events``) and handles a distinct part of the
lifecycle:

- **process_sms_queue** -- Runs every minute. Picks up queued SMS entries,
  selects an available device, dispatches the message, and handles per-entry
  retries on failure.
- **send_balance_reminders** -- Runs daily. Finds overdue Sales Invoices,
  groups them by customer, checks configured reminder intervals, and enqueues
  a reminder SMS for each qualifying customer.
- **retry_failed_sms** -- Runs daily. Re-enqueues failed SMS Queue entries
  whose ``retry_count`` has not yet exceeded the configured maximum, giving
  them another chance to be sent.
- **cleanup_old_logs** -- Runs daily. Deletes SMS Log entries older than the
  configured retention period (default 90 days) to keep the database tidy.
- **reset_daily_quotas** -- Runs daily. Resets the ``sent_today`` counter on
  every SMS Device so that daily sending quotas start fresh.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate, add_days, date_diff, flt

from sms_relay.sms_engine import (
    _select_device,
    _send_to_device,
    _log_sms,
    _enqueue_sms,
    _get_gateway_config,
    _clean_phone,
    _render_template,
    MAX_RETRIES,
)

BATCH_SIZE = 10


def process_sms_queue():
    """Process a batch of queued SMS entries and dispatch them through devices.

    Scheduler event: ``all`` (runs every minute via Frappe scheduler).

    This is the core dispatch loop of the SMS relay. On each invocation it:

    1. Reads the gateway configuration; returns immediately if the gateway is
       disabled.
    2. Fetches up to ``BATCH_SIZE`` (10) SMS Queue entries with status
       ``"Queued"``, ordered by priority (ascending) then creation time
       (ascending).
    3. Dispatches each entry through :func:`_process_single_entry`.
    4. Commits the transaction so that all status changes are persisted.

    Config values read:
        - ``enabled`` (bool): If falsy the function exits early.
        - ``max_retry_count`` (int): Maximum number of retry attempts before
          an entry is permanently marked as ``"Failed"``. Falls back to
          ``MAX_RETRIES`` from ``sms_engine``.

    Side effects:
        - Updates ``status`` on ``SMS Queue`` rows (``"Queued"`` ->
          ``"Sending"`` -> ``"Sent"`` / ``"Failed"``).
        - Increments ``sent_today`` on the ``SMS Device`` used.
        - Creates ``SMS Log`` entries for each dispatched message.
        - Calls ``frappe.db.commit()``.

    Returns:
        None
    """
    config = _get_gateway_config()
    if not config.get("enabled"):
        return

    entries = frappe.get_all(
        "SMS Queue",
        filters={"status": "Queued"},
        fields=["name", "phone", "message", "priority", "reference_doctype",
                "reference_docname", "recipient_name", "retry_count", "template"],
        order_by="priority asc, creation asc",
        limit_page_length=BATCH_SIZE,
    )

    if not entries:
        return

    max_retries = cint(config.get("max_retry_count")) or MAX_RETRIES

    for entry in entries:
        _process_single_entry(entry, config, max_retries)

    frappe.db.commit()


def _process_single_entry(entry, config, max_retries):
    """Dispatch a single SMS Queue entry through an available device.

    This is an internal helper called by :func:`process_sms_queue` for each
    queued entry in the current batch.

    Step-by-step behaviour:

    1. Sets the queue entry status to ``"Sending"``.
    2. Calls ``_select_device(phone)`` to find an eligible device that can
       send to the given phone number (respects country rules, daily quotas,
       and active state).
    3. If no device is available, reverts the status back to ``"Queued"`` and
       logs an error -- the entry will be retried on the next scheduler tick.
    4. Calls ``_send_to_device(device, phone, message)`` which returns a
       ``message_id`` from the underlying gateway.
    5. On success: marks the entry as ``"Sent"``, records the device and
       ``message_id``, updates the device's ``sent_today`` counter, and
       creates an ``SMS Log`` entry.
    6. On failure: increments ``retry_count``. If the count has reached
       ``max_retries``, the entry is permanently marked ``"Failed"``
       (with the error message) and an ``SMS Log`` with ``"Failed"`` status
       is written. Otherwise the entry is returned to ``"Queued"`` status so
       it can be retried later, and an error is logged via
       ``frappe.log_error``.

    Args:
        entry (dict): A dictionary representing one ``SMS Queue`` row with
            keys ``name``, ``phone``, ``message``, ``retry_count``, and
            reference fields.
        config (dict): The gateway configuration dict returned by
            ``_get_gateway_config()``.
        max_retries (int): Maximum number of attempts before the entry is
            considered permanently failed.

    Returns:
        None

    Raises:
        This function catches all exceptions internally so that a single
        entry failure does not abort the entire batch.
    """
    queue_name = entry.name
    phone = entry.phone
    message = entry.message

    try:
        # Mark as sending
        frappe.db.set("SMS Queue", queue_name, "status", "Sending", update_modified=True)

        device = _select_device(phone)
        if not device:
            frappe.db.set("SMS Queue", queue_name, "status", "Queued",
                          update_modified=True)
            frappe.log_error(
                f"SMS Relay: no device available for queue {queue_name}"
            )
            return

        message_id = _send_to_device(device, phone, message)

        frappe.db.set(
            "SMS Queue", queue_name,
            {
                "status": "Sent",
                "device": device.get("name"),
                "message_id": message_id,
                "sent_at": frappe.utils.now_datetime(),
            },
            update_modified=True,
        )

        # Update device sent_today counter
        frappe.db.sql(
            """UPDATE `tabSMS Device`
               SET sent_today = sent_today + 1
               WHERE name = %s""",
            (device.get("name"),),
        )

        _log_sms(
            phone=phone,
            message=message,
            status="Sent",
            device=device.get("name"),
            doctype=entry.get("reference_doctype"),
            docname=entry.get("reference_docname"),
            message_id=message_id,
        )

    except Exception as e:
        retry_count = cint(entry.get("retry_count", 0)) + 1

        if retry_count >= max_retries:
            frappe.db.set(
                "SMS Queue", queue_name,
                {
                    "status": "Failed",
                    "retry_count": retry_count,
                    "error": str(e)[:500],
                },
                update_modified=True,
            )
            _log_sms(
                phone=phone,
                message=message,
                status="Failed",
                doctype=entry.get("reference_doctype"),
                docname=entry.get("reference_docname"),
                error=str(e)[:500],
            )
        else:
            frappe.db.set(
                "SMS Queue", queue_name,
                {
                    "status": "Queued",
                    "retry_count": retry_count,
                },
                update_modified=True,
            )
            frappe.log_error(
                f"SMS Relay: queue {queue_name} failed (attempt {retry_count}/{max_retries}): {e}"
            )


def send_balance_reminders():
    """Send overdue invoice payment-reminder SMS to customers.

    Scheduler event: ``daily`` (runs once per day via Frappe scheduler).

    Step-by-step behaviour:

    1. Reads gateway configuration; returns early if the gateway is disabled
       or if ``send_overdue_reminders`` is not enabled.
    2. Parses ``reminder_intervals`` (comma-separated string of day counts,
       default ``"7,14,30,60,90"``).
    3. Fetches all submitted ``Sales Invoice`` rows with status ``"Overdue"``
       and ``outstanding_amount > 0``.
    4. Groups invoices by customer so each customer receives at most one
       reminder per day.
    5. For each customer group, computes ``days_overdue`` from the earliest
       ``due_date`` among their invoices. If the number of overdue days does
       not match any configured interval, the customer is skipped.
    6. Resolves the customer's phone number via ``_get_customer_phone`` and
       checks the opt-out list. Skips if opted out or no phone found.
    7. Builds a message context (customer name, invoice list, outstanding
       total, currency, days overdue, etc.) and renders the SMS text using
       the configured ``overdue_template`` (falls back to a plain-text
       default if no template is set).
    8. Enqueues the rendered message via ``_enqueue_sms`` at priority 3.

    Config values read:
        - ``enabled`` (bool): Gateway master switch.
        - ``send_overdue_reminders`` (bool): Feature toggle for this task.
        - ``reminder_intervals`` (str): Comma-separated day counts at which
          reminders should be sent (default ``"7,14,30,60,90"``).
        - ``overdue_template`` (str): Name of the SMS/Jinja template to
          render. If empty, a default plain-text message is used.

    Side effects:
        - Enqueues ``SMS Queue`` entries (one per qualifying customer) with
          priority 3. Actual sending happens when ``process_sms_queue``
          picks them up.
        - Reads ``Sales Invoice`` and ``SMS Optout`` doctypes.

    Returns:
        None
    """
    config = _get_gateway_config()
    if not config.get("enabled") or not config.get("send_overdue_reminders"):
        return

    intervals_str = config.get("reminder_intervals") or "7,14,30,60,90"
    try:
        intervals = [cint(x.strip()) for x in intervals_str.split(",") if x.strip()]
    except Exception:
        intervals = [7, 14, 30, 60, 90]

    today = getdate(nowdate())

    # Fetch overdue invoices
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "status": "Overdue",
            "outstanding_amount": (">", 0),
            "docstatus": 1,
        },
        fields=["name", "customer", "due_date", "outstanding_amount",
                "grand_total", "company", "currency"],
    )

    if not invoices:
        return

    # Group by customer to avoid duplicate reminders on the same day
    customer_invoices = {}
    for inv in invoices:
        customer = inv.customer
        if not customer:
            continue
        if customer not in customer_invoices:
            customer_invoices[customer] = []
        customer_invoices[customer].append(inv)

    template_name = config.get("overdue_template")

    for customer, inv_list in customer_invoices.items():
        earliest_due = min(getdate(inv.due_date) for inv in inv_list if inv.due_date)
        days_overdue = date_diff(today, earliest_due)

        if days_overdue not in intervals:
            continue

        phone = _get_customer_phone_via_engine(customer)
        if not phone:
            continue

        from sms_relay.sms_engine import _check_opt_out
        if _check_opt_out(phone):
            continue

        total_outstanding = sum(flt(inv.outstanding_amount) for inv in inv_list)
        currency = inv_list[0].get("currency") or ""

        from frappe.utils import fmt_money
        context = {
            "customer_name": customer,
            "customer": customer,
            "invoice_names": ", ".join(inv.name for inv in inv_list),
            "outstanding_total": fmt_money(total_outstanding, currency=currency),
            "days_overdue": days_overdue,
            "earliest_due_date": earliest_due.strftime("%d-%m-%Y"),
            "invoice_count": len(inv_list),
            "company": inv_list[0].get("company") or "",
        }

        message = _render_template(template_name, context) if template_name else (
            f"Dear {customer}, you have {len(inv_list)} overdue invoice(s) totaling "
            f"{fmt_money(total_outstanding, currency=currency)} "
            f"(overdue {days_overdue} days). Please arrange payment."
        )

        if not message:
            continue

        _enqueue_sms(
            phone=phone,
            message=message,
            recipient_name=customer,
            doctype="Sales Invoice",
            docname=inv_list[0].name,
            priority=3,
            template=template_name,
        )


def retry_failed_sms():
    """Re-enqueue failed SMS Queue entries that still have retry attempts remaining.

    Scheduler event: ``daily`` (runs once per day via Frappe scheduler).

    Step-by-step behaviour:

    1. Reads ``max_retry_count`` from the gateway configuration (falls back
       to ``MAX_RETRIES`` from ``sms_engine``).
    2. Queries all ``SMS Queue`` rows with ``status = "Failed"`` and
       ``retry_count < max_retries``.
    3. For each matching entry, resets ``status`` back to ``"Queued"`` so that
       ``process_sms_queue`` will pick it up on its next tick.
    4. Commits the transaction and logs the number of re-enqueued entries.

    Config values read:
        - ``max_retry_count`` (int): Upper bound on retries. Entries whose
          ``retry_count`` is below this value are re-enqueued.

    Side effects:
        - Updates ``status`` on ``SMS Queue`` rows (``"Failed"`` ->
          ``"Queued"``).
        - Calls ``frappe.db.commit()`` if any entries were re-enqueued.

    Returns:
        None
    """
    config = _get_gateway_config()
    max_retries = cint(config.get("max_retry_count")) or MAX_RETRIES

    failed = frappe.get_all(
        "SMS Queue",
        filters={
            "status": "Failed",
            ("retry_count", "<"): max_retries,
        },
        fields=["name"],
    )

    count = 0
    for entry in failed:
        frappe.db.set("SMS Queue", entry.name, "status", "Queued", update_modified=True)
        count += 1

    if count:
        frappe.db.commit()
        frappe.logger().info(f"SMS Relay: re-enqueued {count} failed SMS entries")


def cleanup_old_logs():
    """Delete SMS Log entries older than the retention period.

    Scheduler event: ``daily`` (runs once per day via Frappe scheduler).

    Step-by-step behaviour:

    1. Computes a cutoff date equal to 90 days before today.
    2. Executes a ``DELETE`` query on ``SMS Log`` for all rows whose
       ``creation`` timestamp is before the cutoff.
    3. If any rows were affected, commits the transaction and logs an
       informational message.

    Config values read:
        None -- the retention period is currently hard-coded to 90 days.

    Side effects:
        - Permanently deletes rows from the ``SMS Log`` doctype table.
        - Calls ``frappe.db.commit()`` if rows were deleted.

    Returns:
        None
    """
    from frappe.utils import add_days

    cutoff = add_days(nowdate(), -90)

    result = frappe.db.sql(
        """DELETE FROM `tabSMS Log`
           WHERE creation < %s""",
        (cutoff,),
    )

    if result and result[0] if isinstance(result, tuple) else result:
        frappe.db.commit()
        frappe.logger().info(f"SMS Relay: cleaned up old SMS logs older than {cutoff}")


def reset_daily_quotas():
    """Reset the daily sending quota counter on all SMS Devices.

    Scheduler event: ``daily`` (runs once per day via Frappe scheduler, ideally
    just before midnight or early morning).

    Step-by-step behaviour:

    1. Sets ``sent_today = 0`` on every row in ``SMS Device``.
    2. Commits the transaction and logs an informational message.

    Config values read:
        None.

    Side effects:
        - Updates ``sent_today`` to ``0`` on **all** ``SMS Device`` rows.
        - Calls ``frappe.db.commit()``.

    Returns:
        None
    """
    frappe.db.sql(
        """UPDATE `tabSMS Device`
           SET sent_today = 0"""
    )
    frappe.db.commit()
    frappe.logger().info("SMS Relay: daily device quotas reset")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_customer_phone_via_engine(customer_name):
    """Import-safe wrapper around ``_get_customer_phone`` from ``sms_engine``.

    This function exists to avoid circular-import issues: ``sms_engine``
    imports from ``tasks`` indirectly through the Frappe hook system, so the
    import of ``_get_customer_phone`` is deferred to call time.

    Args:
        customer_name (str): The name (primary key) of a ``Customer`` doctype
            row whose phone number should be resolved.

    Returns:
        str | None: The cleaned phone number for the customer, or ``None``
        if no phone number could be found.
    """
    from sms_relay.sms_engine import _get_customer_phone
    return _get_customer_phone(customer_name)
