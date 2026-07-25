# SMS Relay

SMS Relay Gateway for Frappe/ERPNext — multi-device SMS routing with queue management, template rendering, and automated document notifications.

## Features

- **Multi-device routing** — Priority-based device selection with health checks, daily quotas, and automatic failover.
- **Async queue** — All outgoing SMS is queued, dispatched by a per-minute scheduler, and retried on failure.
- **Document hooks** — Automatically send SMS on Sales Invoice, Payment Entry, and Payment Request submission.
- **Overdue reminders** — Configurable interval-based payment reminders (e.g., 7, 14, 30, 60, 90 days).
- **Jinja templates** — Render messages with full document context (customer name, amounts, due dates, etc.).
- **Webhook callbacks** — Receive delivery/failure confirmations from gateway devices via HMAC-signed webhooks.
- **Rate limiting** — Per-device throttle and daily quotas to stay within carrier limits.
- **Opt-out support** — Respect SMS opt-out preferences.
- **Dashboard** — Device health indicators, today's stats, and send-SMS button on invoices.
- **REST API** — Whitelisted methods for immediate send, bulk send, stats, retries, and template preview.

## Requirements

- Frappe Framework v14+ / v15+
- ERPNext v14+ (for Sales Invoice, Payment Entry, Payment Request doctypes)
- An SMS gateway device (e.g., Android phone running an SMS gateway app such as [SMS Gateway](https://github.com/bipin2017/sms-gateway) or similar)

## Installation

```bash
cd /path/to/frappe-bench
bench get-app /path/to/sms_relay
bench --site site-name install-app sms_relay
bench --site site-name migrate
bench build --app sms_relay
bench restart
```

Or install from a Git repository:

```bash
bench get-app https://github.com/manaa-soft/sms_relay.git
bench --site site-name install-app sms_relay
bench build --app sms_relay
bench restart
```

## Configuration

### 1. SMS Gateway Settings

Go to **SMS Gateway Settings** in Frappe:

| Field | Description |
|---|---|
| Enabled | Master toggle for SMS sending |
| Gateway URL | Base URL of the SMS gateway device (e.g., `http://192.168.1.100:8080`) |
| API Key | API key for gateway authentication |
| API Secret | API secret (used for webhook HMAC verification) |
| Webhook Secret | Secret for validating incoming webhook signatures |
| Default Sender | Default sender ID / name |
| Send Invoice SMS | Enable automatic SMS on Sales Invoice submit |
| Send Payment SMS | Enable automatic SMS on Payment Entry submit |
| Send Payment Request SMS | Enable automatic SMS on Payment Request submit |
| Send Overdue Reminders | Enable daily overdue invoice reminders |
| Reminder Intervals | Comma-separated days (e.g., `7,14,30,60,90`) |
| Rate Limit | Max SMS per device per minute (default: 30) |
| Max Retry Count | Max retry attempts for failed SMS (default: 3) |

### 2. SMS Devices

Create **SMS Device** records under SMS Device:

| Field | Description |
|---|---|
| Device Name | Human-readable name |
| Gateway URL | Device-specific URL (overrides global) |
| SIM Slot | SIM slot number (1 or 2) |
| Priority | Lower = higher priority (tried first) |
| Daily Quota | Max SMS per day (0 = unlimited) |
| Status | Online / Offline (updated by heartbeat) |

### 3. SMS Templates

Create **SMS Template** records. Templates use Jinja2 syntax. Available variables depend on context:

**Invoice template variables:**
`customer_name`, `invoice_name`, `posting_date`, `due_date`, `total`, `outstanding`, `company`

**Payment template variables:**
`party_name`, `payment_name`, `amount`, `posting_date`, `payment_method`, `company`

**Payment request template variables:**
`party_name`, `request_name`, `amount`, `payment_url`, `company`

**Overdue template variables:**
`customer_name`, `invoice_names`, `outstanding_total`, `days_overdue`, `earliest_due_date`, `invoice_count`

### 4. Webhook Configuration

Configure your SMS gateway device to send delivery reports to:

```
POST /api/method/sms_relay.webhook_receiver.incoming_webhook
Content-Type: application/json

{
    "event": "sms:delivered",
    "message_id": "<id>",
    "device_name": "<device>"
}
```

Supported events: `sms:delivered`, `sms:failed`, `sms:sent`, `system:ping`.

If `Webhook Secret` is configured, the device must include an HMAC-SHA256 `signature` field computed over the JSON payload.

## API Reference

All methods are whitelisted and called via Frappe RPC:

### `sms_relay.api.send_sms_now`

Send an SMS immediately (bypasses queue).

```
recipient: str    # Phone number
message: str      # SMS body
template: str     # Optional template name
device: str       # Optional device name (auto-select if omitted)
sim: int          # Optional SIM slot
```

### `sms_relay.api.send_bulk_sms`

Enqueue SMS for multiple recipients.

```
recipients_csv: str   # Comma/newline-separated phone numbers
message: str          # SMS body
template: str         # Optional template name
```

### `sms_relay.api.get_device_health`

Returns health status of all enabled devices (online/offline, quota, heartbeat).

### `sms_relay.api.preview_template`

Render a template with real document data for preview.

```
template_name: str   # SMS Template name
doc_type: str        # Optional DocType
doc_name: str        # Optional document name
```

### `sms_relay.api.retry_sms`

Re-queue a failed SMS for retry.

```
queue_name: str   # SMS Queue document name
```

### `sms_relay.api.get_sms_stats`

Returns today's sent/failed/pending/delivered counts.

## Scheduler Jobs

| Schedule | Function | Description |
|---|---|---|
| Every minute | `process_sms_queue` | Dispatch queued SMS |
| Daily | `send_balance_reminders` | Overdue invoice notifications |
| Daily | `retry_failed_sms` | Re-enqueue failed SMS |
| Daily | `cleanup_old_logs` | Delete logs older than 90 days |
| Daily | `reset_daily_quotas` | Reset device daily counters |

## License

Apache License 2.0. See [license.txt](license.txt).
