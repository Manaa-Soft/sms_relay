# DocTypes Reference

## SMS Gateway Settings

**Module:** SMS Relay
**Type:** Singleton
**Controller:** `sms_relay.sms_relay.doctype.sms_gateway_settings.sms_gateway_settings`

Global configuration for the entire SMS relay system. Only one record exists.

### Fields

#### General
| Field | Type | Required | Description |
|---|---|---|---|
| enabled | Check | No | Master on/off switch |
| gateway_url | Data | Yes | SMS Gateway server URL |
| api_path | Data | No | API endpoint path (default: `/api/3rdparty/v1/message`) |
| username | Data | Yes | Gateway authentication username |
| password | Password | Yes | Gateway authentication password |
| private_token | Password | No | Bearer token authentication (alternative) |
| timeout | Int | No | HTTP timeout seconds (default: 15) |

#### Notification Settings
| Field | Type | Description |
|---|---|---|
| send_invoice_sms | Check | Auto-send on Sales Invoice submit |
| send_payment_sms | Check | Auto-send on Payment Entry submit |
| send_overdue_reminders | Check | Daily overdue balance reminders |
| reminder_time | Time | Time for reminders (default: 09:00) |
| reminder_intervals | Data | Days after due date (e.g. "7,14,30,60,90") |

#### Queue & Rate Limiting
| Field | Type | Description |
|---|---|---|
| max_retry_count | Int | Max retries for failed SMS (default: 3) |
| rate_limit_per_minute | Int | Per-device per-minute cap (default: 30, max: 60) |
| batch_size | Int | Max SMS per queue cycle (default: 10) |
| log_retention_days | Int | Days to keep logs (default: 90) |

#### Webhook Settings
| Field | Type | Description |
|---|---|---|
| webhook_enabled | Check | Enable delivery receipt webhooks |
| webhook_secret | Password | HMAC-SHA256 verification secret |

#### Compliance
| Field | Type | Description |
|---|---|---|
| check_opt_out | Check | Check opt-out list before sending (default: 1) |

### Validation
- `gateway_url`: trailing slash auto-removed
- `rate_limit_per_minute`: cannot exceed 60

---

## SMS Device

**Module:** SMS Relay
**Type:** Standard
**Controller:** `sms_relay.sms_relay.doctype.sms_device.sms_device`

Represents a registered Android phone connected to the SMS Gateway server.

### Fields

| Field | Type | Required | In List View | Description |
|---|---|---|---|---|
| device_name | Data | Yes | Yes | Human-readable label |
| device_id | Data | No | No | Gateway device ID |
| mode | Select | No | No | Local/Cloud/Private |
| server_url | Data | No | No | Device-specific URL override |
| username | Data | No | No | Device-specific username |
| password | Password | No | No | Device-specific password |
| sim_number | Int | No | Yes | SIM slot (1 or 2) |
| priority | Int | No | Yes | Lower = higher priority |
| is_active | Check | No | Yes | Enable/disable device |
| last_heartbeat | Datetime | No | No | Last system:ping timestamp |
| is_online | Check | No | No | Computed from heartbeat |
| daily_quota | Int | No | No | Max SMS per day (default: 200) |
| sent_today | Int | No | No | Current day counter (auto-reset) |
| country_code | Data | No | No | Default prefix (e.g. +967) |
| notes | Small Text | No | No | Freeform notes |

### Validation
- `sent_today` cannot exceed `daily_quota`

---

## SMS Log

**Module:** SMS Relay
**Type:** Standard (Read-only)
**Controller:** `sms_relay.sms_relay.doctype.sms_log.sms_log`

Immutable audit trail of all SMS activity. Created by the engine and webhook receiver. Cannot be edited by users.

### Fields

| Field | Type | Read-only | In List View | Description |
|---|---|---|---|---|
| phone | Data | Yes | Yes | Recipient phone number |
| recipient_name | Data | Yes | No | Recipient name |
| message | Long Text | Yes | No | SMS body text |
| status | Select | Yes | Yes | Pending/Queued/Sending/Sent/Delivered/Failed/Retrying |
| delivery_status | Select | Yes | No | Pending/Sent/Delivered/Failed/Expired |
| reference_doctype | Link | Yes | No | Source DocType |
| reference_name | Data | Yes | Yes | Source document name |
| gateway_message_id | Data | Yes | Yes | Gateway-assigned message ID |
| device | Link | Yes | No | Sending device |
| sim_number | Int | Yes | No | SIM slot used |
| queued_at | Datetime | Yes | No | When queued |
| sent_at | Datetime | Yes | No | When sent to gateway |
| delivered_at | Datetime | Yes | No | When delivery confirmed |
| retry_count | Int | Yes | No | Number of retries |
| error_message | Long Text | Yes | No | Error details |
| webhook_payload | Code | Yes | No | Raw webhook JSON |

### Permissions
- System Manager: read, delete
- All roles: read

---

## SMS Queue

**Module:** SMS Relay
**Type:** Standard
**Controller:** `sms_relay.sms_relay.doctype.sms_queue.sms_queue`

Async queue for outgoing SMS. Created by handlers/engine, processed by scheduler.

### Fields

| Field | Type | In List View | Description |
|---|---|---|---|
| status | Select | Yes | Queued/Sending/Sent/Failed/Cancelled |
| priority | Int | Yes | Lower = higher priority |
| recipient | Data | Yes | Phone number |
| recipient_name | Data | No | Recipient name |
| message | Long Text | Yes | SMS body |
| reference_doctype | Link | No | Source DocType |
| reference_name | Data | No | Source document name |
| template | Link | No | SMS Template used |
| device | Link | No | Assigned device |
| sim_number | Int | No | SIM slot |
| gateway_message_id | Data | No | Gateway message ID |
| retry_count | Int | No | Current retry count |
| max_retries | Int | No | Max allowed retries |
| error_log | Long Text | No | Error details |
| scheduled_at | Datetime | No | Deferred send time |
| sent_at | Datetime | No | Actual send time |

### Status Flow

```
Queued → Sending → Sent → Delivered
                ↘ Failed (retry_count < max) → Queued (retry)
                ↘ Failed (retry_count >= max) → Failed (permanent)
```

### Permissions
- System Manager: full access
- All roles: read

---

## SMS Template

**Module:** SMS Relay
**Type:** Standard
**Controller:** `sms_relay.sms_relay.doctype.sms_template.sms_template`

Jinja2 message templates for different notification events.

### Fields

| Field | Type | Required | In List View | Description |
|---|---|---|---|---|
| template_name | Data | Yes | Yes | Unique template name |
| event | Select | Yes | Yes | Event type |
| enabled | Check | No | Yes | Enable/disable |
| message_template | Code | Yes | No | Jinja2 body (max 1600 chars) |
| preview_phone | Data | No | No | Test phone for preview |

### Event Options
- Invoice Created
- Payment Received
- Overdue Reminder
- Payment Request
- Delivery Note
- Custom

### Validation
- Minimum 5 characters
- Maximum 1600 characters (SMS limit)

### Permissions
- System Manager: full access
- All roles: read

---

## SMS Opt Out

**Module:** SMS Relay (created by sms_engine if needed)

Maintains a list of phone numbers that have opted out of SMS. Checked by `_check_opt_out()` before every send.

### Fields (expected)

| Field | Type | Description |
|---|---|---|
| phone | Data | Normalized phone number (E.164) |
| opted_out | Check | Whether opted out |
| customer | Link | Associated Customer (optional) |
| reason | Small Text | Reason for opt-out |

### Usage
When `check_opt_out` is enabled in SMS Gateway Settings, the engine checks this table before sending. If a matching phone with `opted_out=1` exists, the SMS is silently skipped.
