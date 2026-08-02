# API Reference

All methods are whitelisted and callable via Frappe RPC (`frappe.call` from JS or `frappe.get_attr` from Python).

## send_sms_now

Send an SMS immediately, bypassing the queue.

**Path:** `sms_relay.api.endpoints.send_sms_now`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| recipient | str or list | Yes | Phone number(s), auto-normalized to E.164 |
| message | str | Yes* | SMS body text |
| template | str | Yes* | SMS Template name (overrides message) |
| device | str | No | Force specific device (auto-select if omitted) |
| sim | int | No | SIM slot (1 or 2) |
| message_id | str | No | Client-supplied unique ID for idempotency (prevents duplicate sends) |
| ttl_seconds | int | No | Time-to-live in seconds (message expires if not sent within window) |
| valid_until | str | No | Absolute expiry time (YYYY-MM-DD HH:MM:SS) |
| schedule_at | str | No | Deferred send time (YYYY-MM-DD HH:MM:SS) |

*Either `message` or `template` is required.

**Returns:**
```json
{
    "status": "sent",
    "recipients": ["+1234567890"],
    "message_length": 45
}
```

If a duplicate `message_id` is detected:
```json
{
    "status": "already_sent",
    "recipients": ["+1234567890"],
    "message_id": "unique-123"
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
| recipients_json | str | Yes* | JSON array with phone fields |
| message | str | Yes* | SMS body text |
| template | str | No | SMS Template name |
| account | str | No | Device name |
| scheduled_at | str | No | Deferred send time (YYYY-MM-DD HH:MM:SS) |

*Either `recipients_csv` or `recipients_json` is required. Either `message` or `template` is required.

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

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| device_name | str | No | SMS Device name. If provided, uses that device's server URL and credentials. Otherwise uses global Gateway Settings. |

**Returns:**
```json
{
    "success": true,
    "device": {
        "id": "device-001",
        "name": "Samsung Galaxy S21",
        "online": true
    }
}
```

---

## connect_device

Fetch device info from the SMS Gateway server and auto-fill SMS Device fields.

**Path:** `sms_relay.api.endpoints.connect_device`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| device_name | str | Yes | SMS Device document name |

**Returns:**
```json
{
    "success": true,
    "updates": {
        "is_online": 1,
        "last_heartbeat": "2026-07-27 10:00:00",
        "device_id": "phone-001",
        "device_model": "Samsung Galaxy S21",
        "carrier_name": "Vodafone",
        "sim_phone_number": "+212600000000",
        "battery_level": 85
    }
}
```

Queries:
- `GET {server_url}/api/mobile/v1/device` — device details (Basic Auth)
- `GET {server_url}/health` — online status (no auth)

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
        "signal_strength": "Connected",
        "sim_slot": 1,
        "gateway_type": "Android SMS Gateway",
        "sent_today": 45,
        "daily_quota": 200,
        "sent_this_hour": 3,
        "hourly_quota": 500,
        "quota_usage_today": "22.5%"
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

## cancel_message

Cancel a queued SMS message before it is sent.

**Path:** `sms_relay.api.endpoints.cancel_message`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| queue_name | str | Yes | SMS Queue document name |

**Returns:**
```json
{
    "status": "cancelled",
    "name": "SMSG-0001"
}
```

---

## get_message_history

Query SMS message history with filtering and pagination.

**Path:** `sms_relay.api.endpoints.get_message_history`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| from_date | str | No | Start date (YYYY-MM-DD) |
| to_date | str | No | End date (YYYY-MM-DD) |
| status | str | No | Filter by status (Sent/Failed/Delivered/etc.) |
| device | str | No | Filter by device name |
| phone | str | No | Filter by phone number (partial match) |
| limit | int | No | Max results (default: 50) |
| offset | int | No | Pagination offset (default: 0) |

**Returns:**
```json
{
    "messages": [
        {
            "name": "SMS-0001",
            "phone": "+1234567890",
            "message": "Hello!",
            "status": "Sent",
            "device": "Office Phone",
            "message_id": "unique-123",
            "creation": "2026-07-27 10:00:00"
        }
    ],
    "total": 150,
    "limit": 50,
    "offset": 0
}
```

---

## get_inbox

Get incoming SMS messages.

**Path:** `sms_relay.api.endpoints.get_inbox`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| from_date | str | No | Start date (YYYY-MM-DD) |
| to_date | str | No | End date (YYYY-MM-DD) |
| phone | str | No | Filter by sender phone |
| limit | int | No | Max results (default: 50) |
| offset | int | No | Pagination offset (default: 0) |

**Returns:**
```json
{
    "messages": [
        {
            "name": "SMSG-0050",
            "recipient": "+1234567890",
            "message": "STOP",
            "status": "Received",
            "creation": "2026-07-27 11:00:00"
        }
    ],
    "total": 5,
    "limit": 50,
    "offset": 0
}
```

---

## get_device_settings

Get device settings from the gateway.

**Path:** `sms_relay.api.endpoints.get_device_settings`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| device_name | str | Yes | SMS Device name |

**Returns:**
```json
{
    "success": true,
    "settings": { ... }
}
```

---

## update_device_settings

Update device settings on the gateway.

**Path:** `sms_relay.api.endpoints.update_device_settings`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| device_name | str | Yes | SMS Device name |
| settings_json | str or dict | Yes | Settings to update (JSON string or object) |

**Returns:**
```json
{
    "success": true
}
```

---

## get_structured_health

Per-device structured health checks with pass/warn/fail status.

**Path:** `sms_relay.api.endpoints.get_structured_health`

**Parameters:** None

**Returns:**
```json
{
    "status": "pass",
    "total_devices": 2,
    "online_devices": 2,
    "checks": [
        {
            "name": "Office Phone",
            "status": "pass",
            "is_online": true,
            "battery_level": 85,
            "sent_today": 45,
            "failed_today": 1,
            "failure_rate": "2.2%",
            "quota_usage": "22.5%"
        }
    ]
}
```

Status logic:
- **pass**: device online, battery > 20%, failure rate normal
- **warn**: battery low (< 20%) or high failure rate
- **fail**: device offline

---

## incoming_webhook

Public endpoint for receiving delivery receipts and incoming SMS.

**Path:** `sms_relay.api.webhook_receiver.incoming_webhook`

**Method:** POST

**Authentication:** None (allow_guest=True), optional HMAC-SHA256

### Request Envelope

The Android SMS Gateway **app** POSTs an envelope (webhooks are sent directly from the phone, not relayed by the server):

```json
{
    "id": "unique-webhook-event-id",
    "webhookId": "webhook-config-id",
    "event": "sms:received",
    "deviceId": "device-001",
    "payload": {
        "messageId": "gateway-message-id",
        "sender": "+1234567890",
        "message": "STOP",
        "simNumber": 1,
        "receivedAt": "2026-08-01T09:00:00Z"
    }
}
```

- `event` and `deviceId` live on the envelope; all event fields are nested inside `payload`.
- Delivery/cancel reports are correlated via `payload.messageId` ↔ `SMS Log.gateway_message_id` (and `SMS Queue.gateway_message_id`, falling back to `name`).
- Plain (non-envelope) bodies are still accepted for backward compatibility.

### Signature Verification

The app signs **every** webhook by default with an auto-generated key. To verify, set **Webhook HMAC Secret** in SMS Relay Settings to the app's signing key. If `Webhook HMAC Secret` is configured, the endpoint accepts **either** scheme:

1. **Android SMS Gateway app** (recommended) — headers `X-Signature` + `X-Timestamp`:
   `X-Signature = HMAC-SHA256(secret, raw_body + X-Timestamp)` where `X-Timestamp` is unix seconds. Freshness window: `now - 900s ≤ ts ≤ now + 60s`. Keep device clocks in sync.
2. **Legacy** — header `X-Webhook-Signature`:
   `X-Webhook-Signature = HMAC-SHA256(secret, raw_body)`.

> **Multi-device:** the signing key is per-device. With more than one phone, either set the same signing key on all of them or leave `Webhook HMAC Secret` empty (idempotency still dedupes replays).

### Delivery Report

```json
{
    "id": "unique-webhook-event-id",
    "webhookId": "webhook-config-id",
    "event": "sms:delivered",
    "deviceId": "device-001",
    "payload": {
        "messageId": "gateway-message-id",
        "recipient": "+1234567890",
        "phoneNumber": "+1234567890"
    }
}
```

`sms:failed` payload may include `reason` (stored in `SMS Log.error_message`); `sms:sent` payload may include `partsCount` (stored in `SMS Log.sms_parts`).

### Incoming SMS

```json
{
    "id": "unique-webhook-event-id",
    "webhookId": "webhook-config-id",
    "event": "sms:received",
    "deviceId": "device-001",
    "payload": {
        "messageId": "gateway-message-id",
        "sender": "+1234567890",
        "recipient": null,
        "simNumber": 1,
        "phoneNumber": "+1234567890",
        "message": "STOP",
        "receivedAt": "2026-08-01T09:00:00Z"
    }
}
```

Canonical fields (inside `payload`): `sender` (fallbacks `phone`/`from`/`phoneNumber`), `simNumber` (→ `SMS Queue.sim_number`), `receivedAt`.

### Data SMS / MMS

`sms:data-received` (`payload.data`), `mms:received` (`payload.subject`, `payload.size`), `mms:downloaded` (`payload.body`, `payload.attachments[].name`) are all stored as received messages.

### App Started

```json
{
    "id": "unique-webhook-event-id",
    "webhookId": "webhook-config-id",
    "event": "app:started",
    "deviceId": "device-001",
    "payload": {
        "simCards": [
            {"slotIndex": 0, "simNumber": 1, "phoneNumber": "+1234567890", "carrierName": "Test Carrier", "iccid": "..."}
        ]
    }
}
```

Updates the matching `SMS Device` (by `device_id`): `is_online`, `last_heartbeat`, and SIM phone number / carrier.

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
| sms:failed | Message delivery failed (captures `reason`) |
| sms:sent | Message accepted by carrier (captures `partsCount`) |
| sms:cancelled | Message was cancelled |
| sms:received | Incoming SMS received |
| sms:data-received | Incoming data SMS received |
| mms:received | MMS notification received |
| mms:downloaded | MMS downloaded (with attachments) |
| app:started | App booted — refreshes device heartbeat/SIM info |
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
| Every minute | process_scheduled_messages | sms_relay.tasks.process_scheduled_messages |
| Every minute | process_outbox | sms_relay.tasks.process_outbox |
| Every minute | process_bulk_messages | sms_relay.tasks.process_bulk_messages |
| Every minute | process_webhook_deliveries | sms_relay.tasks.process_webhook_deliveries |
| Hourly | check_device_health | sms_relay.tasks.check_device_health |
| Daily | send_overdue_reminders | sms_relay.tasks.send_overdue_reminders |
| Daily | retry_failed_sms | sms_relay.tasks.retry_failed_sms |
| Daily | cleanup_old_logs | sms_relay.tasks.cleanup_old_logs |
| Daily | reset_daily_quotas | sms_relay.tasks.reset_daily_quotas |
