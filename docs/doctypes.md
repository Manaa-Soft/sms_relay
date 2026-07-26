# DocTypes Reference

## SMS Gateway Settings

**Module:** SMS Relay | **Type:** Singleton

Global configuration for the entire SMS relay system.

### Fields

#### General
| Field | Type | Description |
|---|---|---|
| enabled | Check | Master on/off toggle |
| sender_name | Data | Default sender label |
| gateway_url | Data | Global gateway server URL |
| api_path | Data | API endpoint path |
| username | Data | Gateway auth username |
| password | Password | Gateway auth password |
| private_token | Password | Bearer token auth (alternative) |
| timeout | Int | HTTP timeout seconds (default: 15) |

#### Routing & Failover
| Field | Type | Description |
|---|---|---|
| routing_strategy | Select | Round Robin / Priority / Random |
| failover_enabled | Check | Use next device if primary fails |
| global_rate_limit | Int | Max SMS per minute across all devices (default: 60) |

#### Webhook Security
| Field | Type | Description |
|---|---|---|
| webhook_secret | Password | HMAC-SHA256 verification secret |
| webhook_signature_header | Data | Header name (default: X-Webhook-Signature) |

---

## SMS Device

**Module:** SMS Relay | **Type:** Standard

Represents a registered Android phone or custom HTTP SMS API endpoint.

### Fields

| Field | Type | In List View | Description |
|---|---|---|---|
| device_name | Data | Yes | Human-readable label |
| gateway_url | Data | Yes | Gateway server URL |
| gateway_type | Select | Yes | Android SMS Gateway / Custom HTTP API |
| api_key | Password | — | Per-device auth token |
| is_active | Check | Yes | Enable/disable device |
| priority | Int | Yes | Lower = higher priority |
| sim_slot | Select | — | SIM slot 1 or 2 |
| battery_level | Int | — | Battery % (read-only) |
| signal_strength | Data | — | Signal info (read-only) |
| hourly_quota | Int | — | Max SMS per hour (default: 500) |
| daily_quota | Int | — | Max SMS per day (default: 5000) |
| webhook_callback_url | Data | — | Delivery report callback URL |

### Device Selection Algorithm

1. Get all Active devices sorted by priority ASC
2. Check daily quota not exhausted
3. Check per-minute rate limit not exceeded
4. Apply routing strategy (Round Robin / Priority / Random)
5. If failover enabled, try next device on failure
6. If no device available → SMS stays in queue

---

## SMS Template

**Module:** SMS Relay | **Type:** Standard

Jinja2 message templates with header/footer and character counting.

### Fields

| Field | Type | Description |
|---|---|---|
| template_name | Data | Unique template name |
| event | Select | Event type |
| enabled | Check | Enable/disable |
| language | Link: Language | Template language |
| header | Small Text | Prepended to message |
| message_template | Code | Jinja2 body |
| footer | Small Text | Appended to message |
| char_count | Int | Character count (read-only) |
| sms_parts | Int | SMS segments (read-only) |

### Template Variables

Use `{{ doc }}` to access the full document object:

```
Dear {{ doc.customer }}, your invoice {{ doc.name }} for {{ frappe.utils.fmt_money(doc.grand_total) }} is due on {{ doc.due_date }}.
```

### Character Counting

- **GSM-7**: 160 chars per SMS, 153 for multi-part
- **Unicode**: 70 chars per SMS, 67 for multi-part
- Counter auto-detects encoding and shows part count

---

## SMS Log

**Module:** SMS Relay | **Type:** Standard (Read-only)

Immutable audit trail of all SMS activity.

### Fields

| Field | Type | In List View | Description |
|---|---|---|---|
| phone_number | Data | Yes | Recipient phone |
| message | Long Text | — | SMS body |
| status | Select | Yes | Queued/Sent/Delivered/Failed/Cancelled |
| delivery_status | Select | Yes | Pending/Sent/Delivered/Failed/Expired |
| delivery_at | Datetime | — | Delivery report timestamp |
| device_name | Link: SMS Device | Yes | Sending device |
| gateway_message_id | Data | Yes | Gateway-assigned ID |
| channel | Data | — | SMS (default) |

---

## SMS Queue

**Module:** SMS Relay | **Type:** Standard

Async message queue with priority tiers and retry support.

### Fields

| Field | Type | In List View | Description |
|---|---|---|---|
| phone_number | Data | Yes | Recipient phone |
| message | Long Text | Yes | SMS body |
| status | Select | Yes | Queued/Sending/Sent/Failed/Received/Cancelled |
| priority_tier | Select | Yes | High/Normal/Low |
| target_sim | Select | — | Auto/1/2 |
| device_name | Link: SMS Device | — | Assigned device |
| max_retries | Int | — | Max retry attempts (default: 3) |
| retry_count | Int | — | Current retry count |
| next_retry_at | Datetime | — | Scheduled retry time |

### Priority Tiers

| Tier | Use Case | Processing |
|---|---|---|
| High | OTP, payment links, alerts | Processed first |
| Normal | Order confirmations, notifications | Standard queue |
| Low | Marketing, newsletters | Processed last |

### Status Flow

```
Queued → Sending → Sent → Delivered
                ↘ Failed (retry_count < max) → Queued (retry with backoff)
                ↘ Failed (retry_count >= max) → Failed (permanent)
```

---

## SMS Opt Out

**Module:** SMS Relay | **Type:** Standard

Blacklist registry for unsubscribed phone numbers.

### Fields

| Field | Type | Description |
|---|---|---|
| phone | Data | Normalized phone (unique) |
| opted_out | Check | Whether opted out |
| reason | Small Text | Reason for opt-out |
| source | Select | Manual / STOP / API |
| opted_out_date | Datetime | When opted out |
| restored_by | Link: User | Who restored (read-only) |
| restored_date | Datetime | When restored (read-only) |

### Usage

When a number is opted out, `sms_engine` checks this table before every send. Opted-out numbers are silently skipped. The opt-out list is cached for 600 seconds.

---

## SMS Bulk Message

**Module:** SMS Relay | **Type:** Standard

Campaign manager for mass SMS messaging.

### Fields

| Field | Type | Description |
|---|---|---|
| message_type | Select | Text / Template |
| message | Long Text | SMS body (for Text type) |
| template | Link: SMS Template | Template name (for Template type) |
| account | Link: SMS Device | Device to use |
| scheduled_at | Datetime | Deferred send time |
| status | Select | Draft/Processing/Completed/Cancelled |
| total_recipients | Int | Total count (read-only) |
| sent_count | Int | Sent count (read-only) |
| failed_count | Int | Failed count (read-only) |
| pending_count | Int | Pending count (read-only) |
| recipients | Table: SMS Bulk Recipient | Recipient list |

---

## SMS Bulk Recipient

**Module:** SMS Relay | **Type:** Child Table

### Fields

| Field | Type | Description |
|---|---|---|
| phone | Data | Phone number (required) |
| recipient_name | Data | Recipient name |
| status | Select | Pending/Sent/Failed |
| error | Small Text | Error message (if failed) |
| message_id | Data | Queue entry name |

---

## SMS Notification

**Module:** SMS Relay | **Type:** Standard

Doc-triggered automated SMS rules with Jinja templates.

### Fields

| Field | Type | Description |
|---|---|---|
| enabled | Check | Enable/disable |
| reference_doctype | Link: DocType | Target DocType |
| event | Select | On Submit / On Save / On Validate |
| account | Link: SMS Device | Device to use |
| phone_field | Data | Field name containing phone number |
| message_template | Code (Jinja) | Message template |
| condition | Code (Python) | "Return True to send" |
| set_property_after_alert | Data | Field to update after sending |
| property_value | Data | Value to set |
| fields | Table: SMS Message Field | Dynamic field mappings |

---

## SMS Notification Log

**Module:** SMS Relay | **Type:** Standard (Read-only)

Delivery audit log linked to specific document events.

### Fields

| Field | Type | Description |
|---|---|---|
| notification | Link: SMS Notification | Source notification |
| reference_doctype | Data | Document type |
| reference_name | Data | Document name |
| phone | Data | Recipient phone |
| message | Long Text | Rendered message |
| status | Select | Sent/Failed |
| sent_at | Datetime | When sent |
| error | Small Text | Error (if failed) |

---

## SMS Outbox

**Module:** SMS Relay | **Type:** Standard (Read-only)

Asynchronous message outbox with exponential backoff retry.

### Fields

| Field | Type | Description |
|---|---|---|
| sms_queue | Link: SMS Queue | Related queue entry |
| channel | Select | SMS |
| account | Link: SMS Device | Sending device |
| status | Select | Pending/Sending/Sent/Failed |
| attempts | Int | Current attempt count |
| max_attempts | Int | Max attempts (default: 5) |
| next_retry_at | Datetime | When to retry next |
| last_retry_at | Datetime | Last attempt time |
| error_message | Long Text | Last error |

### Backoff Schedule

| Attempt | Wait Time |
|---|---|
| 1 | 1 minute |
| 2 | 2 minutes |
| 3 | 4 minutes |
| 4 | 8 minutes |
| 5 | 16 minutes |

---

## SMS Recipient List

**Module:** SMS Relay | **Type:** Standard

Saved target groups for bulk messaging.

### Fields

| Field | Type | Description |
|---|---|---|
| list_name | Data | Unique list name |
| description | Small Text | Description |
| recipients | Table: SMS Recipient | Phone numbers |

---

## SMS Recipient

**Module:** SMS Relay | **Type:** Child Table

### Fields

| Field | Type | Description |
|---|---|---|
| mobile_number | Data | Phone number (required) |
| recipient_name | Data | Recipient name |

---

## SMS Message Field

**Module:** SMS Relay | **Type:** Child Table

Dynamic field mapping for SMS Notification templates.

### Fields

| Field | Type | Description |
|---|---|---|
| field_name | Data | DocType field name |
