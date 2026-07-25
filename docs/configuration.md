# Configuration Guide

## SMS Gateway Settings

Navigate to: **SMS Relay → SMS Gateway Settings** (or Setup → SMS Gateway Settings)

This is a singleton DocType — only one record exists, shared across the entire site.

### General

| Field | Type | Default | Description |
|---|---|---|---|
| Enabled | Check | 0 | Master toggle. When off, no SMS is sent by any hook or scheduler. |
| Server URL | Data | — | Base URL of the SMS Gateway server (e.g. `http://192.168.1.15:3000`). Trailing slash auto-removed. |
| API Path | Data | `/api/3rdparty/v1/message` | HTTP endpoint path for sending SMS. |
| Username | Data | — | Gateway authentication username. |
| Password | Password | — | Gateway authentication password. |
| Private Token | Password | — | Alternative auth method. Sent as `Bearer` token in Authorization header. |
| Timeout | Int | 15 | HTTP request timeout in seconds. |

### Notification Toggles

| Field | Type | Default | Description |
|---|---|---|---|
| Send Invoice SMS | Check | 0 | Auto-send SMS when Sales Invoice is submitted. |
| Send Payment SMS | Check | 0 | Auto-send SMS when Payment Entry is submitted. |
| Send Overdue Reminders | Check | 0 | Enable daily overdue balance reminder SMS. |
| Reminder Time | Time | 09:00 | Time of day to send overdue reminders (informational). |
| Reminder Intervals | Data | `7,14,30,60,90` | Comma-separated days after due date to send reminders. Only sends if `days_overdue` matches one of these values. |

### Queue & Rate Limiting

| Field | Type | Default | Description |
|---|---|---|---|
| Max Retry Count | Int | 3 | Maximum retry attempts for failed SMS before marking as permanently Failed. |
| Rate Limit | Int | 30 | Maximum SMS per device per minute. Prevents carrier throttling. Max allowed: 60. |
| Batch Size | Int | 10 | Maximum SMS processed per scheduler cycle (every minute). |
| Log Retention | Int | 90 | Days to keep SMS Log entries. Older entries deleted by daily cleanup job. |

### Webhook Settings

| Field | Type | Default | Description |
|---|---|---|---|
| Webhook Enabled | Check | 0 | Enable receiving delivery receipts from devices. |
| Webhook HMAC Secret | Password | — | Secret for HMAC-SHA256 signature verification. Device must compute signature over JSON payload. |

### Compliance

| Field | Type | Default | Description |
|---|---|---|---|
| Check Opt-Out List | Check | 1 | Check SMS Opt Out table before sending. Opted-out numbers are silently skipped. |

---

## SMS Device

Navigate to: **SMS Relay → SMS Device → New**

Each registered Android phone is represented by an SMS Device record.

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| Device Name | Data | Yes | Human-readable label (e.g. "Office Phone"). |
| Device ID | Data | No | Gateway device ID. Auto-detected on first heartbeat. |
| Connection Mode | Select | No | Local / Cloud / Private. Affects how the phone connects. |
| Server URL | Data | No | Device-specific gateway URL override. Leave empty to use global. |
| Username | Data | No | Device-specific credentials override. |
| Password | Password | No | Device-specific password override. |
| SIM Number | Int | No | SIM slot to use (1 or 2). Default: 1. |
| Priority | Int | No | Lower = higher priority. Device with priority 0 is tried first. |
| Active | Check | Yes | Enable/disable device. Disabled devices are never selected. |
| Daily Quota | Int | 200 | Maximum SMS per day. Counter resets at midnight. |
| Default Country Code | Data | `+967` | Prepended to local numbers without country code. |
| Notes | Small Text | No | Freeform notes about the device. |

### Status Fields (Read-only)

| Field | Description |
|---|---|
| Last Heartbeat | Timestamp of last `system:ping` from device. |
| Is Online | Based on heartbeat within last 5 minutes. |
| Sent Today | Counter of SMS sent today. Resets daily. |

### Device Selection Algorithm

When sending an SMS, the engine selects the best device:

1. Get all Active devices, sorted by Priority ASC (lowest first)
2. Skip devices with `sent_today >= daily_quota` (quota exhausted)
3. Skip devices with `last_heartbeat` older than 5 minutes (offline)
4. Skip devices that hit rate limit (cache-based, per-minute)
5. First device passing all checks is selected
6. If no device available → SMS stays in queue, retried next cycle

---

## SMS Template

Navigate to: **SMS Relay → SMS Template → New**

Templates use Jinja2 syntax. Available variables depend on the event type.

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| Template Name | Data | Yes | Unique name (e.g. "Invoice Notification"). |
| Event | Select | Yes | Invoice Created / Payment Received / Overdue Reminder / Payment Request / Custom. |
| Enabled | Check | Yes | Toggle to enable/disable template. |
| Message Template | Code | Yes | Jinja2 template body. Max 1600 characters. |
| Preview Phone | Data | No | Phone number for testing preview. |

### Template Variables by Event

#### Invoice Created
| Variable | Type | Description |
|---|---|---|
| `doc` | Document | Full Sales Invoice document object |
| `customer_name` | str | Customer name |
| `invoice_name` | str | Invoice ID (e.g. "SINV-00001") |
| `posting_date` | str | Formatted date (DD-MM-YYYY) |
| `due_date` | str | Formatted due date |
| `total` | str | Formatted grand total with currency |
| `outstanding` | str | Formatted outstanding amount |
| `company` | str | Company name |
| `items` | list | List of {item_name, qty, amount} |

#### Payment Received
| Variable | Type | Description |
|---|---|---|
| `party_name` | str | Customer/Supplier name |
| `payment_name` | str | Payment Entry ID |
| `amount` | str | Formatted paid amount |
| `posting_date` | str | Formatted date |
| `payment_method` | str | Mode of payment |
| `reference` | str | Reference document name |
| `company` | str | Company name |

#### Overdue Reminder
| Variable | Type | Description |
|---|---|---|
| `customer_name` | str | Customer name |
| `invoice_names` | str | Comma-separated invoice IDs |
| `outstanding_total` | str | Total outstanding across all invoices |
| `days_overdue` | int | Days since earliest due date |
| `earliest_due_date` | str | Formatted earliest due date |
| `invoice_count` | int | Number of overdue invoices |

#### Payment Request
| Variable | Type | Description |
|---|---|---|
| `party_name` | str | Customer/Supplier name |
| `request_name` | str | Payment Request ID |
| `amount` | str | Requested amount |
| `payment_url` | str | Payment URL link |
| `company` | str | Company name |

### Example Templates

**Invoice:**
```
Dear {{ customer_name }}, your invoice {{ invoice_name }} for {{ total }} is due on {{ due_date }}. Outstanding: {{ outstanding }}. Thank you!
```

**Payment:**
```
Dear {{ party_name }}, payment of {{ amount }} received on {{ posting_date }}. Ref: {{ payment_name }}. Thank you!
```

**Overdue:**
```
Dear {{ customer_name }}, you have {{ invoice_count }} overdue invoice(s) totaling {{ outstanding_total }} ({{ days_overdue }} days overdue). Please arrange payment.
```

---

## Webhook Configuration

### In SMS Gateway Server (config.yml)

```yaml
server:
  webhooks:
    - url: "http://YOUR-FRAPPE-SITE/api/method/sms_relay.webhook_receiver.incoming_webhook"
      events:
        - sms:delivered
        - sms:failed
        - system:ping
```

### HMAC Signature (Optional)

If `Webhook HMAC Secret` is configured in SMS Gateway Settings:

1. Device computes `HMAC-SHA256(secret, sorted_json_payload_without_signature)`
2. Adds `signature` field to payload
3. Server verifies signature before processing

---

## Environment Variables

The app reads configuration from the Frappe site config via `SMS Gateway Settings` DocType. No environment variables are required.

## Caching

- Gateway config is cached for 120 seconds (in `frappe.cache`)
- Throttle counters are cached per-device for 60 seconds
- Cache is automatically invalidated on settings save
