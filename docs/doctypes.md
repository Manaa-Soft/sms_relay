# DocTypes Reference

## SMS Gateway Settings

**Module:** SMS Relay | **Type:** Singleton

Global configuration for the entire SMS relay system.

### Fields

#### Gateway
| Field | Type | Description |
|---|---|---|
| enabled | Check | Master on/off toggle |
| gateway_url | Data | Gateway server URL (e.g. `http://192.168.1.15:8085`) |
| api_path | Data | API endpoint path (default: `/api/3rdparty/v1/message`) |
| private_token | Password | Bearer token for server-level auth (overrides device username/password) |
| timeout | Int | HTTP timeout seconds (default: 15) |
| max_retry_count | Int | Max retry attempts (default: 3) |

#### Routing & Rate Limiting
| Field | Type | Description |
|---|---|---|
| routing_strategy | Select | Round Robin / Priority / Random |
| failover_enabled | Check | Use next device if primary fails |
| global_rate_limit | Int | Max SMS per minute across all devices (default: 60) |
| check_opt_out | Check | Skip opted-out numbers |

#### Webhook (Incoming SMS)
| Field | Type | Description |
|---|---|---|
| webhook_enabled | Check | Enable incoming webhooks |
| webhook_secret | Password | HMAC-SHA256 verification secret |

---

## SMS Device

**Module:** SMS Relay | **Type:** Standard

Represents a registered Android phone or custom HTTP SMS API endpoint.

### Fields

#### Connection
| Field | Type | Description |
|---|---|---|
| device_name | Data | Human-readable label |
| device_id | Data | Unique ID from phone app |
| mode | Select | Android SMS Gateway / Custom HTTP API |
| server_url | Data | Gateway server URL for this device |
| username | Data | Gateway auth username |
| password | Password | Gateway auth password |
| sim_number | Select | SIM slot 1 or 2 |
| priority | Int | Lower = higher priority |
| is_active | Check | Enable/disable device |

#### Status (Read-only)
| Field | Type | Description |
|---|---|---|
| is_online | Check | Whether device is reachable |
| last_heartbeat | Datetime | Last successful communication |
| device_model | Data | Phone model |
| app_version | Data | SMS Gateway app version |
| battery_level | Int | Battery percentage |
| signal_strength | Data | Network signal info |
| carrier_name | Data | Mobile carrier |
| sim_phone_number | Data | SIM phone number |

#### Quotas
| Field | Type | Description |
|---|---|---|
| daily_quota | Int | Max SMS per day (default: 5000) |
| sent_today | Int | Current day count (read-only) |
| hourly_quota | Int | Max SMS per hour (default: 500) |

#### Additional
| Field | Type | Description |
|---|---|---|
| country_code | Data | Default country code for phone normalization |
| notes | Small Text | Internal notes |

### Device Selection Algorithm

1. Get all Active devices (`is_active = 1`) sorted by priority ASC
2. Check daily quota not exhausted
3. Apply routing strategy (Round Robin / Priority / Random)
4. If failover enabled, try next device on failure
5. If no device available → SMS stays in queue

---

## SMS Template

**Module:** SMS Relay | **Type:** Standard

Jinja2 message templates with header/footer, positional parameters, and character counting.

### Fields

| Field | Type | Description |
|---|---|---|
| template_name | Data | Unique template name |
| event | Select | Event type |
| enabled | Check | Enable/disable |
| language | Link: Language | Template language |
| header | Small Text | Prepended to message |
| message_template | Code | Jinja2 body — supports `{{ doc.field }}` and `{{1}}`, `{{2}}` positional params |
| footer | Small Text | Appended to message |
| char_count | Int | Character count (read-only) |
| sms_parts | Int | SMS segments (read-only) |

### Message Syntax

Two syntaxes are supported (can be mixed):

1. **Jinja2**: `{{ doc.field_name }}` — rendered against the document at runtime.
2. **Positional**: `{{1}}`, `{{2}}`, `{{N}}` — replaced from the **Fields** child table rows in the linked SMS Notification.

### Character Counting

- **GSM-7**: 160 chars per SMS, 153 for multi-part
- **Unicode**: 70 chars per SMS, 67 for multi-part
- Counter auto-detects encoding and shows part count

---

## SMS Log

**Module:** SMS Relay | **Type:** Standard (Read-only)

Immutable audit trail of all SMS activity.

### Fields

| Field | Type | Description |
|---|---|---|
| phone | Data | Recipient phone |
| recipient_name | Data | Recipient name |
| message | Long Text | SMS body |
| status | Select | Queued/Sent/Delivered/Failed/Cancelled |
| delivery_status | Select | Pending/Sent/Delivered/Failed/Expired |
| delivery_at | Datetime | Delivery report timestamp |
| channel | Data | SMS (default) |
| reference_doctype | Data | Source DocType (if from notification) |
| reference_name | Data | Source document name |
| gateway_message_id | Data | Gateway-assigned ID |
| device | Link: SMS Device | Sending device |
| sim_number | Data | SIM slot used |
| queued_at | Datetime | When queued |
| sent_at | Datetime | When sent |
| delivered_at | Datetime | When delivered |
| retry_count | Int | Number of retries |
| error_message | Small Text | Error (if failed) |
| webhook_payload | Long Text | Raw webhook data |

---

## SMS Queue

**Module:** SMS Relay | **Type:** Standard

Async message queue with priority tiers and retry support.

### Fields

| Field | Type | Description |
|---|---|---|
| status | Select | Queued/Sending/Sent/Failed/Received/Cancelled |
| priority | Int | Sort order (lower = higher priority) |
| priority_tier | Select | High/Normal/Low |
| recipient | Data | Recipient phone |
| recipient_name | Data | Recipient name |
| message | Long Text | SMS body |
| reference_doctype | Data | Source DocType |
| reference_name | Data | Source document name |
| template | Link: SMS Template | Source template |
| device | Link: SMS Device | Assigned device |
| sim_number | Data | Target SIM slot |
| gateway_message_id | Data | Gateway-assigned ID |
| retry_count | Int | Current retry count |
| max_retries | Int | Max retries (default: 3) |
| error_log | Small Text | Error details |
| scheduled_at | Datetime | Deferred send time |
| sent_at | Datetime | When sent |

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

Doc-triggered automated SMS rules with Jinja or Parameter templates.

### Fields

| Field | Type | Description |
|---|---|---|
| notification_name | Data | Unique name |
| notification_type | Select | DocType notification / Scheduler Event |
| disabled | Check | Disable this rule |
| reference_doctype | Link: DocType | Target DocType |
| doctype_event | Select | On Submit / On Save / On Validate / On Payment / On Cancel / On TRASH |
| field_name | Data | Field containing phone number |
| template | Link: SMS Template | Linked template |
| template_type | Select | **Jinja** or **Parameter** — controls how the template body is rendered |
| message_template | Code (Jinja) | Template body |
| condition | Code (Python) | `return True` to send |
| event_frequency | Select | How often to trigger |
| days_in_advance | Int | For scheduled: days before date field |
| date_changed | Select | Date/Datetime field to check (auto-populated from DocType) |
| set_property_after_alert | Data | Field to update after sending |
| property_value | Data | Value to set |
| fields | Table: SMS Message Field | Positional parameter mappings (Parameter mode only) |

### Template Type

| Type | Syntax | When to use |
|---|---|---|
| **Jinja** | `{{ doc.field_name }}` | Full access to document fields, Jinja2 filters, conditionals |
| **Parameter** | `{{1}}`, `{{2}}` | Simple positional replacement — maps each number to a field via the Fields table |

In **Jinja** mode, the Fields table is hidden. In **Parameter** mode, the Fields table is visible and each row maps a `{{N}}` placeholder to a DocType field name.

### Positional Parameters (Parameter Mode)

The **Fields** child table maps `{{1}}`, `{{2}}`, etc. in the message template to document fields:

| Row | `{{1}}` resolves to | `{{2}}` resolves to |
|---|---|---|
| 1 | Row 1's `field_name` value | — |
| 2 | Row 1's `field_name` value | Row 2's `field_name` value |

Example template:
```
Hello {{1}}, your order {{2}} is ready. Total: {{3}}
```
Fields table:
| # | field_name |
|---|---|
| 1 | customer_name |
| 2 | name |
| 3 | grand_total |

Result: `Hello John, your order SO-00123 is ready. Total: 1500.00`

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

Positional parameter mapping for SMS Notification templates.
Each row maps a `{{N}}` placeholder to a document field name.

### Fields

| Field | Type | Description |
|---|---|---|
| field_name | Data | DocType field name — value of `{{1}}`, `{{2}}`, etc. |
