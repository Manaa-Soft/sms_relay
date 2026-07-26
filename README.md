# SMS Relay

Frappe/ERPNext SMS gateway integration. Multi-device routing, bulk messaging, Jinja/Parameter templates, delivery tracking, and automated document hooks — all via Android SMS Gateway or custom HTTP SMS APIs.

## Architecture

```
ERPNext (Invoice/Payment/Delivery/PO)
        │
  hooks.py doc_events["*"]
        │
  utils/__init__.py (notification map + after_commit dispatch)
        │
  SMS Notification (Jinja render / positional param replacement + condition check)
        │
  SMS Queue (priority tiers: High/Normal/Low)
        │
  sms_engine.py (device routing: Round Robin / Priority / Random)
        │
  Android Phone via Docker Server (Basic Auth → /api/3rdparty/v1/message)
        │
  webhook_receiver.py (delivery receipts + incoming SMS)
```

### Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Frappe/ERPNext → Docker Server                                          │
│                                                                         │
│ POST /api/3rdparty/v1/message                                           │
│ Auth: Basic Auth (username:password from SMS Device record)             │
│ Response: 202 Accepted                                                  │
│                                                                         │
│ The Docker server validates credentials against its MySQL database.     │
│ Credentials are the login:password returned when the phone registered.  │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ Phone App → Docker Server                                               │
│                                                                         │
│ Device Registration:                                                    │
│   POST /api/mobile/v1/device                                            │
│   Auth: Bearer <private_token> (private mode) or Basic Auth             │
│   Response: { login, password, token, id }                              │
│                                                                         │
│ Polling Messages:                                                       │
│   GET /api/mobile/v1/message                                            │
│   Auth: Bearer <device_token>                                           │
│                                                                         │
│ The phone then sends SMS via the physical SIM card.                     │
└─────────────────────────────────────────────────────────────────────────┘
```

## Features

- **Multi-device routing** — Round Robin, Priority, or Random selection with failover
- **Bulk messaging** — CSV upload, recipient lists, batch processing with progress tracking
- **Document notifications** — Jinja or Parameter templates triggered on any DocType event
- **Template types** — Jinja (`{{ doc.field }}`) or Parameter (`{{1}}`, `{{2}}` positional)
- **Async queue** — Priority tiers (High for OTP/Payment, Low for marketing)
- **SMS Opt Out** — Automatic STOP blacklist with cache invalidation
- **Delivery tracking** — Webhook delivery receipts with HMAC-SHA256 verification
- **Device health monitoring** — Battery, signal strength, SIM info, hourly/daily quotas
- **Character counter** — GSM-7 (160 chars) vs Unicode (70 chars) detection, multi-part SMS calculation
- **REST API** — Send, bulk, health, preview, retry, stats, notification preview, test connection, connect device
- **Dashboard** — Real-time device health, daily stats, auto-refresh
- **Desk sidebar** — Appears in Frappe v16/v17 sidebar navigation

## Requirements

- Frappe Framework v15+ (tested on v16)
- ERPNext v15+ (for Sales Invoice, Payment Request, Delivery Note, Purchase Order)
- [Android SMS Gateway](https://github.com/AuroraLS/android-sms-gateway) server running in Docker
- At least one Android phone connected to the gateway

## Installation

```bash
cd /path/to/frappe-bench

bench get-app https://github.com/Manaa-Soft/sms_relay.git
bench --site your-site install-app sms_relay
bench migrate
bench build --app sms_relay
bench restart
```

## Quick Start

### 1. Configure SMS Gateway Settings

**SMS Relay → SMS Gateway Settings**

| Field | Description |
|---|---|
| Enabled | Master on/off toggle |
| Server URL | Gateway server URL (e.g. `http://192.168.1.15:8085`) |
| API Path | Endpoint path (default: `/api/3rdparty/v1/message`) |
| Timeout | HTTP timeout in seconds |
| Routing Strategy | Round Robin / Priority / Random |
| Enable Failover | Use next device if primary fails |
| Global Rate Limit | Max SMS per minute across all devices |
| Check Opt-Out | Skip opted-out numbers |
| Enable Incoming Webhooks | Receive delivery receipts |

### 2. Add SMS Devices

**SMS Relay → SMS Device → New**

| Field | Description |
|---|---|
| Device Name | Human-readable label (e.g. "Office Phone") |
| Device ID | Unique ID from the phone app |
| Mode | Local / Cloud / Private |
| Server URL | Gateway server URL for this device |
| Username / Password | Per-device authentication (the credentials returned when the phone registered with the Docker server) |
| SIM Number | SIM slot (1 or 2) |
| Priority | Lower = higher priority |
| Hourly/Daily Quota | Rate limits |
| Active | Enable/disable |

Click **Connect Device** to auto-fetch device info from the gateway.

### 3. Create SMS Templates (Optional)

**SMS Relay → SMS Template → New**

Use Jinja2 syntax with `{{ doc }}` to access document fields:

```
Dear {{ doc.customer }}, your invoice {{ doc.name }} for {{ frappe.utils.fmt_money(doc.grand_total) }} is due on {{ doc.due_date }}. Please pay at your earliest convenience.
```

Or use positional parameters mapped via SMS Notification Fields table:

```
Hello {{1}}, your order {{2}} is ready. Total: {{3}}
```

### 4. Set Up Notifications

**SMS Relay → SMS Notification → New**

Configure document-triggered SMS:
- **Notification Type**: DocType notification
- **Reference DocType**: Sales Invoice, Payment Request, etc.
- **DocType Event**: On Submit / On Save / On Validate
- **Field Name**: Field containing phone number
- **Template**: Link to an SMS Template
- **Template Type**: **Jinja** (use `{{ doc.field }}` syntax) or **Parameter** (use `{{1}}`, `{{2}}` mapped via Fields table)
- **Message Template**: Template body (auto-loaded from linked template)
- **Fields** (Parameter mode only): Map each `{{N}}` to a DocType field name
- **Condition**: Python expression (e.g., `return doc.grand_total > 1000`)

### 5. Test

```javascript
frappe.call({
    method: "sms_relay.api.endpoints.send_sms_now",
    args: {
        recipient: "+1234567890",
        message: "Test SMS from SMS Relay!"
    }
});
```

## DocTypes (14 Total)

### New DocTypes (9)

| DocType | Purpose |
|---|---|
| SMS Opt Out | STOP blacklist registry |
| SMS Bulk Message | Campaign manager with CSV upload |
| SMS Bulk Recipient | Child table for bulk recipients |
| SMS Notification | Doc-triggered automated SMS rules with Jinja or Parameter templates |
| SMS Notification Log | Delivery audit log per document event |
| SMS Outbox | Async outbox with exponential backoff retry |
| SMS Recipient List | Saved target groups (e.g., "VIP Customers") |
| SMS Recipient | Child table for recipient lists |
| SMS Message Field | Dynamic field mapping for positional parameters in notifications |

### Enhanced Existing (5)

| DocType | Enhancements |
|---|---|
| SMS Gateway Settings | Routing strategy, rate limiting, webhook secret, failover |
| SMS Device | Server URL, username/password, SIM info, device model, carrier, battery, quotas, Connect Device / Send Test SMS buttons |
| SMS Template | Language, header/footer, character counter, positional param support |
| SMS Log | Delivery status, delivery timestamp, channel, retry count |
| SMS Queue | Priority tiers, target SIM, retry counts |

## API Reference

All methods called via Frappe RPC (`frappe.call`).

### send_sms_now

```javascript
frappe.call({
    method: "sms_relay.api.endpoints.send_sms_now",
    args: {
        recipient: "+1234567890",
        message: "Hello!",
        template: "Payment Reminder",  // optional
        device: "Phone A",            // optional, auto-select
        sim: 1                        // optional
    }
});
```

### send_bulk_sms

```javascript
frappe.call({
    method: "sms_relay.api.endpoints.send_bulk_sms",
    args: {
        recipients_csv: "phone,name\n+1234567890,John\n+0987654321,Jane",
        message: "Payment reminder",
        account: "Phone A",           // optional
        scheduled_at: "2026-07-27 09:00:00"  // optional
    }
});
```

### Other Endpoints

| Method | Description |
|---|---|
| `sms_relay.api.endpoints.test_connection` | Test gateway connectivity (accepts optional `device_name` arg) |
| `sms_relay.api.endpoints.connect_device` | Fetch device info from gateway (requires `device_name`) |
| `sms_relay.api.endpoints.get_device_health` | Device health, battery, signal, quota usage |
| `sms_relay.api.endpoints.preview_template` | Render template with real document data |
| `sms_relay.api.endpoints.retry_sms` | Re-queue a failed SMS |
| `sms_relay.api.endpoints.get_sms_stats` | Today's sent/failed/delivered/queued counts |
| `sms_relay.api.endpoints.get_notification_preview` | Preview notification output with sample doc |

### Webhook

```
POST http://your-frappe-site/api/method/sms_relay.api.webhook_receiver.incoming_webhook

{
    "event": "sms:delivered",
    "id": "message-id",
    "phoneNumber": "+1234567890"
}
```

Supported events: `sms:delivered`, `sms:failed`, `sms:sent`, `sms:received`, `system:ping`

## Scheduled Jobs

| Schedule | Job | Description |
|---|---|---|
| Every minute | `process_sms_queue` | Flush queued SMS to devices |
| Every minute | `process_outbox` | Process outbox with exponential backoff |
| Every minute | `process_bulk_messages` | Process bulk campaign batches |
| Hourly | `check_device_health` | Heartbeat, battery, signal checks |
| Daily | `send_overdue_reminders` | Overdue invoice notifications |
| Daily | `retry_failed_sms` | Re-enqueue retryable failures |
| Daily | `cleanup_old_logs` | Purge old SMS Log entries (90-day retention) |
| Daily | `reset_daily_quotas` | Reset device daily counters |

## Module Structure

```
sms_relay/sms_relay/
├── core/
│   ├── sms_engine.py          # Device routing, gateway dispatch, E.164 normalization
│   ├── notification_handler.py # Doc-event triggers with Jinja
│   ├── bulk_engine.py          # CSV import, batch processing
│   └── sms_utils.py            # Phone utils, GSM-7, HMAC verify
├── api/
│   ├── webhook_receiver.py     # Incoming SMS + delivery reports
│   └── endpoints.py            # REST API endpoints
├── utils/
│   ├── __init__.py             # Notification map, after_commit dispatch, scheduler triggers
│   ├── jinja_methods.py        # Custom Jinja filters
│   └── contact_manager.py      # Auto-link SMS to Contact/Lead
├── doctype/                    # 14 DocTypes (9 new + 5 enhanced)
├── public/js/
│   ├── sms_dashboard.js        # Real-time monitoring
│   ├── bulk_message.js         # Bulk composer with progress
│   └── notification_builder.js # Visual rule builder
├── hooks.py
├── tasks.py
└── setup.py
```

## License

Apache License 2.0. See [license.txt](license.txt).
