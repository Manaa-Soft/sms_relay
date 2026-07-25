# API Reference

All methods are whitelisted and callable via Frappe RPC (`frappe.call` from client-side JS or `frappe.get_attr` from Python).

## send_sms_now

Send an SMS immediately, bypassing the queue.

**Path:** `sms_relay.api.send_sms_now`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| recipient | str | Yes | Phone number (any format, auto-normalized to E.164) |
| message | str | Yes | SMS body text (max 1600 chars recommended) |
| template | str | No | SMS Template name to render (overrides message) |
| device | str | No | Force specific device name (auto-select if omitted) |
| sim | int | No | SIM slot number (1 or 2) |

**Returns:**
```python
{
    "status": "sent",
    "message_id": "abc123",  # Gateway message ID
    "device": "My Phone",    # Device that sent it
    "phone": "+967712345678" # Normalized phone
}
```

**Raises:**
- `frappe.ValidationError` — invalid phone, opted out, no device available, empty message

**Example (JS):**
```javascript
frappe.call({
    method: "sms_relay.api.send_sms_now",
    args: {
        recipient: "+967712345678",
        message: "Hello from ERPNext!"
    },
    callback: function(r) {
        console.log(r.message);
    }
});
```

## send_bulk_sms

Enqueue SMS for multiple recipients from a CSV string.

**Path:** `sms_relay.api.send_bulk_sms`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| recipients_csv | str | Yes | Comma/semicolon/newline-separated phone numbers |
| message | str | Yes | SMS body text |
| template | str | No | SMS Template name |

**Returns:**
```python
{
    "status": "queued",
    "queued": 15,          # Successfully enqueued
    "skipped_opt_out": 2,  # Skipped (opted out)
    "invalid": 1           # Invalid phone numbers
}
```

**Example (JS):**
```javascript
frappe.call({
    method: "sms_relay.api.send_bulk_sms",
    args: {
        recipients_csv: "+967712345678\n+967798765432",
        message: "Payment reminder: you have an outstanding balance."
    },
    callback: function(r) {
        frappe.show_alert("Queued: " + r.message.queued);
    }
});
```

## get_device_health

Returns health status of all enabled SMS devices.

**Path:** `sms_relay.api.get_device_health`

**Parameters:** None

**Returns:**
```python
[
    {
        "device": "SMS Device-001",
        "device_name": "My Phone",
        "online": true,
        "status": "Online",
        "priority": 0,
        "sim_slot": 1,
        "sent_today": 45,
        "daily_quota": 200,
        "quota_remaining": 155,
        "last_heartbeat": "2026-07-26 10:30:00"
    }
]
```

**Note:** A device is considered "online" if its last heartbeat was within 5 minutes.

## preview_template

Render an SMS template with optional real document data.

**Path:** `sms_relay.api.preview_template`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| template_name | str | Yes | SMS Template name |
| doc_type | str | No | DocType to load context from |
| doc_name | str | No | Document name to load |

**Returns:**
```python
{
    "template": "Invoice Notification",
    "rendered": "Dear ABC Corp, your invoice SINV-001 for 1,500.00 SAR...",
    "context_keys": ["doc", "customer_name", "grand_total", "due_date", ...]
}
```

## retry_sms

Manually retry a failed SMS Queue entry.

**Path:** `sms_relay.api.retry_sms`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| queue_name | str | Yes | SMS Queue document name |

**Returns:**
```python
{
    "status": "requeued",
    "name": "SMS Queue-001"
}
```

**Note:** Only entries with status "Failed" or "Sent" can be retried. Retry count is reset to 0.

## get_sms_stats

Returns today's SMS statistics.

**Path:** `sms_relay.api.get_sms_stats`

**Parameters:** None

**Returns:**
```python
{
    "sent": 120,
    "failed": 3,
    "pending": 5,
    "delivered": 95,
    "total": 223,
    "date": "2026-07-26"
}
```

## incoming_webhook

Public endpoint for receiving delivery receipts from SMS gateway devices.

**Path:** `sms_relay.webhook_receiver.incoming_webhook`

**Method:** POST

**Authentication:** None (allow_guest=True), optional HMAC-SHA256 signature

**Request Body:**
```json
{
    "event": "sms:delivered",
    "message_id": "abc123",
    "device_name": "My Phone",
    "phone": "+967712345678",
    "error": "",
    "signature": "hmac-sha256-hex-digest"
}
```

**Supported Events:**

| Event | Description | Required Fields |
|---|---|---|
| sms:delivered | Message delivered to recipient | message_id, device_name |
| sms:failed | Message delivery failed | message_id, device_name, error |
| sms:sent | Message accepted by carrier | message_id, device_name |
| system:ping | Device heartbeat | device_name |

**Response:**
```json
{"status": "ok"}
```

**Error Responses:**
- 400: Invalid JSON, empty payload, unknown event
- 403: Invalid HMAC signature

## Hook Entry Points

### send_sms (Frappe Hook)
**Path:** `sms_relay.sms_engine.send_sms`

Called by Frappe's `send_sms()` mechanism. Routes all outgoing SMS through the relay engine instead of the default provider.

**Parameters:** Same as Frappe's standard `send_sms()` — `receiver_list`, `msg`, `sender_name`, `success_msg`

### send_sms_override (Whitelisted Method Override)
**Path:** `sms_relay.sms_engine.send_sms_override`

Overrides `frappe.core.doctype.sms_settings.sms_settings.send_sms`. Accepts `recipient` (str or list), `message`, `sender`.

## Document Event Hooks

| Document | Event | Handler |
|---|---|---|
| Sales Invoice | on_submit | sms_relay.handlers.on_invoice_submit |
| Payment Entry | on_submit | sms_relay.handlers.on_payment_submit |
| Payment Request | on_submit | sms_relay.handlers.on_payment_request_submit |

## Scheduled Jobs

| Frequency | Function | Path |
|---|---|---|
| Every minute | process_sms_queue | sms_relay.tasks.process_sms_queue |
| Daily | send_balance_reminders | sms_relay.tasks.send_balance_reminders |
| Daily | retry_failed_sms | sms_relay.tasks.retry_failed_sms |
| Daily | cleanup_old_logs | sms_relay.tasks.cleanup_old_logs |
| Daily | reset_daily_quotas | sms_relay.tasks.reset_daily_quotas |
