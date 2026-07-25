# SMS Relay

Frappe/ERPNext app for sending SMS via a private Android SMS Gateway server. Multi-device routing, async queue, delivery tracking, and automated document notifications.

## How It Works

```
ERPNext (Invoice/Payment)
        |
  sms_relay hooks
        |
  SMS Queue (priority + TTL)
        |
  Device Selector (health, quota, priority)
        |
  Android Phone (via SMS Gateway server)
        |
  Delivery Webhook --> Frappe (status updated)
```

## Features

- **Multi-device routing** — Priority-based device selection with health checks, daily quotas, and automatic failover
- **Async queue** — All outgoing SMS is queued, dispatched per-minute, retried on failure
- **Document hooks** — Auto-send SMS on Sales Invoice, Payment Entry, Payment Request submit
- **Overdue reminders** — Configurable interval-based payment reminders (e.g. 7, 14, 30, 60, 90 days)
- **Jinja templates** — Render messages with full document context
- **Webhook delivery receipts** — Receive delivery/failure confirmations with HMAC verification
- **Rate limiting** — Per-device throttle and daily quotas
- **Opt-out support** — Check opt-out list before sending
- **Dashboard** — Device health, today's stats, send-SMS button on invoices
- **REST API** — Immediate send, bulk send, stats, retries, template preview

## Requirements

- Frappe Framework v15+
- ERPNext v15+ (for Sales Invoice, Payment Entry, Payment Request)
- [Android SMS Gateway](https://github.com/bipin2017/sms-gateway) server running in Docker
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

## Configuration

### 1. SMS Gateway Settings (Setup > SMS Gateway Settings)

| Field | Description |
|---|---|
| Enabled | Master on/off toggle |
| Server URL | Gateway server URL (e.g. `http://192.168.1.15:3000`) |
| API Path | Endpoint path (default: `/api/3rdparty/v1/message`) |
| Username | Gateway username |
| Password | Gateway password |
| Private Token | Alternative auth (Bearer token) |
| Timeout | HTTP timeout in seconds (default: 15) |
| Send Invoice SMS | Auto-send on Sales Invoice submit |
| Send Payment SMS | Auto-send on Payment Entry submit |
| Send Overdue Reminders | Daily overdue balance notifications |
| Reminder Time | When to send reminders (default: 09:00) |
| Reminder Intervals | Days after due date (e.g. `7,14,30,60,90`) |
| Max Retry Count | Retries for failed SMS (default: 3) |
| Rate Limit | Per-device per-minute cap (default: 30) |
| Batch Size | Max SMS per queue cycle (default: 10) |
| Log Retention | Days to keep SMS logs (default: 90) |
| Webhook Enabled | Receive delivery receipts |
| Webhook HMAC Secret | Secret for webhook signature verification |
| Check Opt-Out List | Skip opted-out numbers |

### 2. SMS Devices (SMS Relay > SMS Device)

| Field | Description |
|---|---|
| Device Name | Human-readable label |
| Device ID | Gateway device ID (auto-detected) |
| Connection Mode | Local / Cloud / Private |
| Server URL | Device-specific URL override |
| Username / Password | Device-specific credentials |
| SIM Number | SIM slot (1 or 2) |
| Priority | Lower = higher priority (tried first) |
| Active | Enable/disable device |
| Daily Quota | Max SMS per day |
| Default Country Code | Prefix for local numbers (e.g. `+967`) |

### 3. SMS Templates (SMS Relay > SMS Template)

Templates use Jinja2 syntax. Create one per event type.

**Available variables by event:**

| Event | Variables |
|---|---|
| Invoice Created | `doc`, `customer_name`, `grand_total`, `due_date`, `outstanding_amount`, `name`, `currency` |
| Payment Received | `doc`, `party_name`, `paid_amount`, `posting_date`, `name`, `reference_name` |
| Overdue Reminder | `doc`, `customer_name`, `name`, `outstanding_amount`, `due_date`, `days_overdue` |
| Payment Request | `doc`, `party_name`, `amount`, `payment_url`, `name` |

### 4. Webhook Configuration

Point your SMS Gateway server to send delivery reports to:

```
POST http://your-frappe-site/api/method/sms_relay.webhook_receiver.incoming_webhook
Content-Type: application/json

{
    "event": "sms:delivered",
    "message_id": "<gateway_message_id>",
    "device_name": "<device>"
}
```

Supported events: `sms:delivered`, `sms:failed`, `sms:sent`, `system:ping`

## API Reference

All methods called via Frappe RPC (`frappe.call`).

### Send Immediately

```javascript
frappe.call({
    method: "sms_relay.api.send_sms_now",
    args: {
        recipient: "+967712345678",
        message: "Your invoice #SINV-001 is ready.",
        template: "Invoice Created",  // optional
        device: "Phone A",           // optional, auto-select if omitted
        sim: 1                       // optional
    }
});
```

### Bulk Send

```javascript
frappe.call({
    method: "sms_relay.api.send_bulk_sms",
    args: {
        recipients_csv: "+967712345678,+967798765432",
        message: "Payment reminder: you have an outstanding balance."
    }
});
```

### Other Endpoints

| Method | Description |
|---|---|
| `sms_relay.api.get_device_health` | Device online/offline status, quota, heartbeat |
| `sms_relay.api.preview_template` | Render template with real doc data |
| `sms_relay.api.retry_sms` | Re-queue a failed SMS |
| `sms_relay.api.get_sms_stats` | Today's sent/failed/pending/delivered counts |

## Scheduled Jobs

| Schedule | Job | Description |
|---|---|---|
| Every minute | `process_sms_queue` | Dispatch queued SMS to devices |
| Daily | `send_balance_reminders` | Overdue invoice notifications |
| Daily | `retry_failed_sms` | Re-enqueue failed SMS |
| Daily | `cleanup_old_logs` | Delete logs older than retention period |
| Daily | `reset_daily_quotas` | Reset device daily counters |

## DocTypes

| DocType | Description |
|---|---|
| SMS Gateway Settings | Singleton — global config |
| SMS Device | Registered Android phone |
| SMS Template | Jinja2 message templates |
| SMS Queue | Pending/outgoing messages |
| SMS Log | Complete SMS history with delivery status |

## License

Apache License 2.0. See [license.txt](license.txt).
