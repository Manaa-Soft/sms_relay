# API Reference

All methods are whitelisted and callable via Frappe RPC (`frappe.call` from JS or `frappe.get_attr` from Python).

## send_sms_now

Send an SMS immediately, bypassing the queue.

**Path:** `sms_relay.api.endpoints.send_sms_now`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| recipient | str or list | Yes | Phone number(s), auto-normalized to E.164 |
| message | str | Yes | SMS body text |
| template | str | No | SMS Template name (overrides message) |
| device | str | No | Force specific device (auto-select if omitted) |
| sim | int | No | SIM slot (1 or 2) |

**Returns:**
```json
{
    "status": "sent",
    "recipients": ["+1234567890"],
    "message_length": 45
}
```

**Example:**
```javascript
frappe.call({
    method: "sms_relay.api.endpoints.send_sms_now",
    args: {
        recipient: "+1234567890",
        message: "Hello from ERPNext!"
    },
    callback: function(r) {
        console.log(r.message);
    }
});
```

---

## send_bulk_sms

Create a bulk SMS campaign from CSV.

**Path:** `sms_relay.api.endpoints.send_bulk_sms`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| recipients_csv | str | Yes* | CSV with phone,name columns |
| message | str | Yes* | SMS body text |
| template | str | No | SMS Template name |
| account | str | No | Device name |
| scheduled_at | str | No | Deferred send time (YYYY-MM-DD HH:MM:SS) |

*Either `recipients_csv` or `recipients_json` is required.

**Returns:**
```json
{
    "status": "created",
    "bulk_job": "BULK-0001",
    "total_recipients": 150
}
```

---

## test_connection

Test connectivity to the SMS gateway server.

**Path:** `sms_relay.api.endpoints.test_connection`

**Parameters:** None

**Returns:**
```json
{
    "success": true,
    "status_code": 200,
    "response": "..."
}
```

---

## connect_device

Fetch device info from the SMS Gateway server and auto-fill SMS Device fields.

**Path:** `sms_relay.api.endpoints.connect_device`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| server_url | str | Yes | Gateway server URL (e.g. `http://192.168.1.15:8085`) |
| username | str | Yes | Gateway auth username |
| password | str | Yes | Gateway auth password |

**Returns:**
```json
{
    "success": true,
    "device_id": "phone-001",
    "device_model": "Samsung Galaxy S21",
    "carrier_name": "Vodafone",
    "sim_phone_number": "+212600000000",
    "app_version": "1.67.0",
    "battery_level": 85,
    "is_online": true
}
```

Queries:
- `GET {server_url}/api/mobile/v1/device` — device details
- `GET {server_url}/health` — online status

---

## get_device_health

Returns health status of all enabled SMS devices.

**Path:** `sms_relay.api.endpoints.get_device_health`

**Parameters:** None

**Returns:**
```json
[
    {
        "name": "SMS Device-001",
        "device_name": "Office Phone",
        "is_active": true,
        "battery_level": 85,
        "signal_strength": "-75 dBm",
        "sim_number": "1",
        "carrier_name": "Vodafone",
        "device_model": "Samsung Galaxy S21",
        "app_version": "1.67.0",
        "sent_today": 45,
        "daily_quota": 5000,
        "sent_this_hour": 3,
        "hourly_quota": 500,
        "quota_usage_today": "0.9%"
    }
]
```

---

## preview_template

Render an SMS template with real document data.

**Path:** `sms_relay.api.endpoints.preview_template`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| template_name | str | Yes* | SMS Template name |
| doc_type | str | No | DocType to load context from |
| doc_name | str | No | Document name |
| message_text | str | Yes* | Direct message text to analyze |

*Either `template_name` or `message_text` is required.

**Returns:**
```json
{
    "message": "Dear ABC Corp, your invoice SINV-001 for 1,500.00 USD...",
    "sms_info": {
        "parts": 1,
        "encoding": "GSM-7",
        "chars": 120,
        "max_chars": 160
    }
}
```

---

## retry_sms

Re-queue a failed SMS for retry.

**Path:** `sms_relay.api.endpoints.retry_sms`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| queue_name | str | Yes | SMS Queue document name |

**Returns:**
```json
{
    "status": "requeued",
    "name": "SMS Queue-001"
}
```

---

## get_sms_stats

Returns today's SMS statistics.

**Path:** `sms_relay.api.endpoints.get_sms_stats`

**Parameters:** None

**Returns:**
```json
{
    "sent_today": 120,
    "failed_today": 3,
    "delivered_today": 95,
    "queued": 5,
    "total_devices": 3,
    "active_devices": 2,
    "opted_out_count": 12
}
```

---

## get_notification_preview

Preview a notification's output with a sample document.

**Path:** `sms_relay.api.endpoints.get_notification_preview`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| notification_name | str | Yes | SMS Notification name |
| doc_type | str | No | DocType to test with |
| doc_name | str | No | Document name to test with |

**Returns:**
```json
{
    "notification": "RNOTIF-0001",
    "reference_doctype": "Sales Invoice",
    "event": "On Submit",
    "message": "Dear ABC Corp, your invoice SINV-001 is ready...",
    "sms_info": {
        "parts": 1,
        "encoding": "GSM-7",
        "chars": 85,
        "max_chars": 160
    }
}
```

---

## incoming_webhook

Public endpoint for receiving delivery receipts and incoming SMS.

**Path:** `sms_relay.api.webhook_receiver.incoming_webhook`

**Method:** POST

**Authentication:** None (allow_guest=True), optional HMAC-SHA256

### Delivery Report

```json
{
    "event": "sms:delivered",
    "id": "message-id-from-gateway",
    "phoneNumber": "+1234567890"
}
```

### Incoming SMS

```json
{
    "event": "sms:received",
    "from": "+1234567890",
    "message": "STOP",
    "profileName": "John Doe"
}
```

### Heartbeat

```json
{
    "event": "system:ping",
    "deviceId": "device-001"
}
```

**Supported Events:**

| Event | Description |
|---|---|
| sms:delivered | Message delivered to recipient |
| sms:failed | Message delivery failed |
| sms:sent | Message accepted by carrier |
| sms:received | Incoming SMS received |
| system:ping | Device heartbeat |

**Response:**
```json
{"status": "ok"}
```

---

## Hook Entry Points

### send_sms_override (Whitelisted Method Override)

**Path:** `sms_relay.core.sms_engine.send_sms_override`

Overrides `frappe.core.doctype.sms_settings.sms_settings.send_sms`. All outgoing SMS is routed through the relay engine.

## Scheduled Jobs

| Frequency | Function | Path |
|---|---|---|
| Every minute | process_sms_queue | sms_relay.tasks.process_sms_queue |
| Every minute | process_outbox | sms_relay.tasks.process_outbox |
| Every minute | process_bulk_messages | sms_relay.tasks.process_bulk_messages |
| Hourly | check_device_health | sms_relay.tasks.check_device_health |
| Daily | send_overdue_reminders | sms_relay.tasks.send_overdue_reminders |
| Daily | retry_failed_sms | sms_relay.tasks.retry_failed_sms |
| Daily | cleanup_old_logs | sms_relay.tasks.cleanup_old_logs |
| Daily | reset_daily_quotas | sms_relay.tasks.reset_daily_quotas |
