import csv
import io
import frappe
from frappe import _
from frappe.utils import now, cint
from sms_relay.core.sms_utils import clean_phone, get_relay_settings, is_opted_out

def create_bulk_job(message_type, message=None, template=None, recipients_csv=None, account=None, scheduled_at=None):
    if message_type == "Text" and not message:
        frappe.throw(_("Message is required for Text type"))
    if message_type == "Template" and not template:
        frappe.throw(_("Template is required for Template type"))
    bulk = frappe.new_doc("SMS Bulk Message")
    bulk.message_type = message_type
    bulk.message = message
    bulk.template = template
    bulk.account = account
    if scheduled_at:
        bulk.scheduled_at = scheduled_at
    if recipients_csv:
        _load_csv_recipients(bulk, recipients_csv)
    bulk.insert(ignore_permissions=True)
    frappe.db.commit()
    return bulk

def create_bulk_from_recipient_list(list_name, message, template=None, message_type="Text", account=None):
    recipient_list = frappe.get_doc("SMS Recipient List", list_name)
    bulk = frappe.new_doc("SMS Bulk Message")
    bulk.message_type = message_type
    bulk.message = message
    bulk.template = template
    bulk.account = account
    for item in recipient_list.recipients:
        bulk.append("recipients", {
            "phone": item.mobile_number,
            "recipient_name": item.recipient_name,
            "status": "Pending",
        })
    bulk.total_recipients = len(bulk.recipients)
    bulk.pending_count = bulk.total_recipients
    bulk.insert(ignore_permissions=True)
    frappe.db.commit()
    return bulk

def _load_csv_recipients(bulk, csv_content):
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            phone = row.get("phone") or row.get("mobile") or row.get("number") or ""
            name = row.get("name") or row.get("recipient_name") or ""
            if phone:
                bulk.append("recipients", {
                    "phone": phone.strip(),
                    "recipient_name": name.strip(),
                    "status": "Pending",
                })
    except Exception as e:
        frappe.throw(_("Error parsing CSV: {}").format(str(e)))

def process_bulk_job(bulk_name):
    bulk = frappe.get_doc("SMS Bulk Message", bulk_name)
    if bulk.status not in ("Draft", "Processing"):
        return
    if bulk.status == "Draft":
        bulk.status = "Processing"
        bulk.started_at = now()
        bulk.save(ignore_permissions=True)
        frappe.db.commit()
    batch_size = 10
    pending = [r for r in bulk.recipients if r.status == "Pending"]
    if not pending:
        bulk.status = "Completed"
        bulk.completed_at = now()
        bulk.save(ignore_permissions=True)
        frappe.db.commit()
        return
    batch = pending[:batch_size]
    for entry in batch:
        phone = clean_phone(entry.phone)
        if is_opted_out(phone):
            entry.status = "Failed"
            entry.error = "Number is opted out"
            bulk.failed_count = cint(bulk.failed_count) + 1
            bulk.pending_count = cint(bulk.pending_count) - 1
            continue
        message = _resolve_message(bulk, phone)
        if not message:
            entry.status = "Failed"
            entry.error = "Could not resolve message"
            bulk.failed_count = cint(bulk.failed_count) + 1
            bulk.pending_count = cint(bulk.pending_count) - 1
            continue
        queue = _enqueue_bulk_sms(phone, message, bulk.account)
        entry.status = "Sent"
        entry.message_id = queue.name
        bulk.sent_count = cint(bulk.sent_count) + 1
        bulk.pending_count = cint(bulk.pending_count) - 1
    bulk.save(ignore_permissions=True)
    frappe.db.commit()
    still_pending = [r for r in bulk.recipients if r.status == "Pending"]
    if not still_pending:
        bulk.reload()
        bulk.status = "Completed"
        bulk.completed_at = now()
        bulk.save(ignore_permissions=True)
        frappe.db.commit()

def _resolve_message(bulk, phone):
    if bulk.message_type == "Text":
        return bulk.message
    if bulk.message_type == "Template" and bulk.template:
        from sms_relay.core.sms_engine import _render_template
        return _render_template(bulk.template, {"phone": phone})
    return bulk.message

def _enqueue_bulk_sms(phone, message, account=None):
    queue = frappe.new_doc("SMS Queue")
    queue.recipient = phone
    queue.message = message
    queue.status = "Queued"
    queue.priority_tier = "Normal"
    queue.max_retries = 3
    if account:
        queue.device = account
    queue.insert(ignore_permissions=True)
    frappe.db.commit()
    return queue

def update_bulk_counts(bulk_name):
    bulk = frappe.get_doc("SMS Bulk Message", bulk_name)
    bulk.total_recipients = len(bulk.recipients)
    bulk.sent_count = len([r for r in bulk.recipients if r.status == "Sent"])
    bulk.failed_count = len([r for r in bulk.recipients if r.status == "Failed"])
    bulk.pending_count = len([r for r in bulk.recipients if r.status == "Pending"])
    bulk.save(ignore_permissions=True)
    frappe.db.commit()

def cancel_bulk_job(bulk_name):
    bulk = frappe.get_doc("SMS Bulk Message", bulk_name)
    if bulk.status == "Completed":
        frappe.throw(_("Cannot cancel a completed bulk job"))
    bulk.status = "Cancelled"
    bulk.save(ignore_permissions=True)
    frappe.db.commit()
