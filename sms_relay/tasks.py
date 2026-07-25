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
    """Process queued SMS entries every minute via scheduler."""
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
    """Dispatch a single queue entry through an available device."""
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
    """Daily job – send overdue invoice reminders based on configured intervals."""
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
    """Daily job – re-enqueue SMS Queue entries that failed but haven't exceeded max retries."""
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
    """Daily job – delete SMS Log entries older than 90 days."""
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
    """Daily job – reset sent_today counter on all SMS Devices."""
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
    """Import-safe wrapper for _get_customer_phone."""
    from sms_relay.sms_engine import _get_customer_phone
    return _get_customer_phone(customer_name)
