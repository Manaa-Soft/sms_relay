# Configuration Guide

## SMS Gateway Settings

Navigate to: **SMS Relay → SMS Gateway Settings**

Singleton DocType — one record for the entire site.

### Gateway

| Field | Type | Default | Description |
|---|---|---|---|---|
| Enabled | Check | 1 | Master toggle. When off, no SMS is sent. |
| Server URL | Data | — | Gateway server URL (e.g. `http://192.168.1.15:8085`). |
| API Path | Data | /api/3rdparty/v1/message | API endpoint path. Used to derive the API base (`/api/3rdparty/v1`). |
| Timeout | Int | 15 | HTTP timeout in seconds. |
| Max Retry Count | Int | 3 | Default retry attempts for failed sends. |

### Gateway Client & Sync

| Field | Type | Default | Description |
|---|---|---|---|
| Webhook URL | Data | — | Public URL the gateway POSTs webhooks to. Empty = auto-detect the site's webhook endpoint. |
| Use JWT Authentication | Check | 0 | Issue scoped JWT tokens via `POST /auth/token` instead of Basic auth. Falls back to Basic if the server rejects the token request. |
| JWT Token TTL (seconds) | Int | 3600 | Token lifetime requested from the gateway. |
| Enable Inbox Sync | Check | 0 | Hourly backfill of the device inbox into SMS Queue (status Received). |
| Enable Delivery Status Sync | Check | 1 | Hourly reconciliation of sent messages via the gateway when webhook reports are missing. |
| Status Sync Age (minutes) | Int | 30 | Only poll messages sent more than this many minutes ago. |

### Routing & Rate Limiting

| Field | Type | Default | Description |
|---|---|---|---|
| Routing Strategy | Select | Round Robin | How to select among multiple devices. |
| Enable Failover | Check | 1 | Try next device if primary fails. |
| Global Rate Limit | Int | 60 | Max SMS per minute across all devices. |
| Check Opt-Out | Check | 1 | Skip opted-out numbers before sending. |
| Send Interval Min | Int | 0 | Minimum delay between sends in seconds. |
| Send Interval Max | Int | 0 | Maximum delay between sends in seconds. |
| Rate Limit Period | Select | Per Minute | Per-device rate limit period: Per Minute / Per Hour / Per Day. |
| Per-Device Rate Limit | Int | 0 | Max SMS per device per rate limit period (0 = unlimited). |
| Device Active Within | Int | 0 | Skip devices inactive for more than N hours (0 = no filter). |

### Routing Strategies

| Strategy | Behavior |
|---|---|
| Round Robin | Rotate through devices sequentially |
| Priority | Try highest-priority device first, fall through on failure |
| Random | Random device selection |

### Webhook (Incoming SMS)

| Field | Type | Default | Description |
|---|---|---|---|
| Enable Incoming Webhooks | Check | 0 | Receive delivery receipts and incoming SMS. |
| Webhook HMAC Secret | Password | — | Secret for verifying webhook signatures (header: `X-Webhook-Signature`). |
| Webhook Max Retries | Int | 15 | Max retry attempts for failed webhook deliveries. |
| Webhook Base Delay | Int | 30 | Exponential backoff base delay in seconds. |

---

## SMS Device

Navigate to: **SMS Relay → SMS Device → New**

Each Android phone or HTTP SMS API endpoint is a separate Device record.

### Connection

| Field | Type | Required | Description |
|---|---|---|---|
| Device Name | Data | Yes | Human-readable label (e.g. "Office Phone"). |
| Device ID | Data | No | Unique ID from the phone app. Filled by Connect Device. |
| Mode | Select | Yes | Local / Cloud / Private. |
| Server URL | Data | Yes | Gateway server URL for this device (e.g. `http://192.168.1.15:8085`). |
| Username | Data | No | Gateway auth username (the `login` returned during phone registration). |
| Password | Password | No | Gateway auth password (the `password` returned during phone registration). |
| SIM Number | Select | No | SIM slot 1 or 2. |
| Priority | Int | No | Lower = higher priority. |
| Active | Check | Yes | Enable/disable device. |
| Webhook Callback URL | Data | No | Overrides the webhook URL used for this device's self-registered webhooks. |
| Webhook Registrations | Code (JSON) | No | Gateway webhook ids provisioned for this device (auto-managed, read-only). |

### Status (Read-only)

| Field | Description |
|---|---|
| Online | Whether the device is reachable (from Connect Device or health check) |
| Last Heartbeat | Last successful communication time |
| Device Model | Phone model (auto-detected) |
| App Version | SMS Gateway app version |
| Battery Level | Battery percentage |
| Signal Strength | Network signal info |
| Carrier Name | Mobile carrier |
| SIM Phone Number | Phone number of the SIM |

### Quotas

| Field | Type | Default | Description |
|---|---|---|---|
| Daily Quota | Int | 200 | Max SMS per day. Resets daily. |
| Sent Today | Int | 0 | Current day count (read-only). |
| Hourly Quota | Int | 500 | Max SMS per hour. |

### Connect Device Button

Click **Connect Device** in the form to auto-fetch device info from the gateway:
- Queries `GET {server_url}/api/mobile/v1/device` for device details (with Basic Auth)
- Queries `GET {server_url}/health` for online status
- Auto-fills: `device_id`, `device_model`, `carrier_name`, `sim_phone_number`, `app_version`, `battery_level`
- **Automatically registers all gateway webhooks** for the device (see `register_device_webhooks`), so no manual app-side webhook setup is required.

### Send Test SMS Button

Click **Send Test SMS** to send a test message through this device.

---

## SMS Template

Navigate to: **SMS Relay → SMS Template → New**

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| Template Name | Data | Yes | Unique name. |
| Language | Link: Language | No | Template language. |
| Header | Small Text | No | Prepended to every message. |
| Message Template | Code | Yes | Jinja2 body — supports `{{ doc.field }}` and `{{1}}`, `{{2}}` positional params. |
| Footer | Small Text | No | Appended to every message. |
| Char Count | Int | No | Character count (read-only). |
| SMS Parts | Int | No | SMS segments (read-only). |

### Template Variables

Two syntaxes are supported (can be mixed):

**Jinja2 syntax** — access any document field:
```
Dear {{ doc.customer }}, your invoice {{ doc.name }} for {{ frappe.utils.fmt_money(doc.grand_total) }} is due on {{ doc.due_date }}.
```

**Positional syntax** — `{{1}}`, `{{2}}` etc. mapped via the SMS Notification **Fields** child table:
```
Hello {{1}}, your order {{2}} is ready. Total: {{3}}
```
In the notification's **Fields** table, row 1 maps to `customer_name`, row 2 to `name`, row 3 to `grand_total`.

### Custom Jinja Filters

| Filter | Usage | Description |
|---|---|---|
| `money` | `{{ doc.grand_total \| money }}` | Format as currency |
| `date_fmt` | `{{ doc.due_date \| date_fmt }}` | Format date (DD-MM-YYYY) |
| `phone_fmt` | `{{ phone \| phone_fmt }}` | Format phone for display |
| `sms_count` | `{{ message \| sms_count }}` | Show SMS segment info |
| `clean_phone` | `{{ phone \| clean_phone }}` | Normalize to E.164 |

---

## SMS Notification

Navigate to: **SMS Relay → SMS Notification → New**

Configure automatic SMS triggers on ERPNext documents.

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| Notification Name | Data | Yes | Unique name. |
| Notification Type | Select | Yes | DocType Event / Scheduler Event. |
| Disabled | Check | No | Disable this rule. |
| Reference DocType | Link: DocType | Yes | Target DocType (Sales Invoice, etc.). |
| DocType Event | Select | Yes | On Submit / On Save / On Validate / etc. |
| Field Name | Data | Yes | Field containing phone number. |
| Template | Link: SMS Template | Yes | Linked SMS Template. |
| Template Type | Select | Yes | **Jinja** (`{{ doc.field }}` syntax) or **Parameter** (`{{1}}`, `{{2}}` mapped via Fields table). |
| Message Template | Code (HTML) | Yes | Template body (auto-loaded from linked template). |
| Condition | Code (Python) | No | `return True` to send. |
| Event Frequency | Select | No | How often to trigger (for scheduled notifications). |
| Scheduler Data Source | Select | No | `Overdue Invoices`: send one message per overdue Sales Invoice (submitted, outstanding balance past due date). Template is chosen per recipient from the invoice/Customer language (Arabic → "…(Arabic)" variant). |
| Fields | Table: SMS Message Field | No | Maps `{{1}}`, `{{2}}` placeholders to document fields (Parameter mode only). |

### Template Types

| Type | Syntax | Fields Table | Example |
|---|---|---|---|
| **Jinja** | `{{ doc.field_name }}` | Hidden | `Dear {{ doc.customer }}, your invoice {{ doc.name }} is due.` |
| **Parameter** | `{{1}}`, `{{2}}` | Visible | `Hello {{1}}, your order {{2}} is ready.` |

### Positional Parameters (Parameter Mode)

Add rows to the **Fields** child table to map `{{1}}`, `{{2}}`, etc. to document fields:

| # | field_name | Resolves `{{N}}` to |
|---|---|---|
| 1 | customer_name | `{{1}}` = document's customer_name value |
| 2 | name | `{{2}}` = document's name value |
| 3 | grand_total | `{{3}}` = document's grand_total value |

You can mix both syntaxes in **Jinja** mode — Jinja2 `{{ doc.field }}` and positional `{{1}}` work together.

### Condition Examples

```python
# Only send for invoices over 1000
return doc.grand_total > 1000

# Only send if customer has outstanding
return doc.outstanding_amount > 0

# Only send on specific payment method
return doc.mode_of_payment == "Bank Transfer"
```

### Phone Resolution Order

1. `field_name` value on the document
2. Customer/Supplier linked Contact phone
3. Document `mobile_no` or `phone` field

---

## Webhook Configuration

### Automatic Self-Registration (recommended)

SMS Relay provisions webhooks itself against the gateway's 3rd-party API. On **Connect Device** (or by calling `register_device_webhooks` / `reconcile_webhooks`), it registers every supported event:

- `POST /webhooks` for each event (`sms:delivered`, `sms:failed`, `sms:sent`, `sms:cancelled`, `sms:received`, `sms:data-received`, `mms:received`, `mms:downloaded`, `app:started`, `system:ping`)
- Registrations are stored on the SMS Device (`Webhook Registrations`) and kept up to date by `reconcile_webhooks` (stray/mismatched URLs are deleted).

This replaces the manual `config.yml` / app-side webhook setup below.

### Manual (In SMS Gateway Server config.yml)

Only needed when running without self-registration (e.g. the server does not expose the webhook API):

```yaml
server:
  webhooks:
    - url: "http://YOUR-FRAPPE-SITE/api/method/sms_relay.api.webhook_receiver.incoming_webhook"
      events:
        - sms:delivered
        - sms:failed
        - sms:sent
        - sms:cancelled
        - sms:received
        - sms:data-received
        - mms:received
        - mms:downloaded
        - app:started
        - system:ping
```

### HMAC Signature Verification

The Android SMS Gateway **app signs every webhook by default** (it auto-generates a random signing key). To enable verification:

1. Open the app → **Webhooks** settings and copy the **signing key**.
2. Paste it into **SMS Relay Settings → Webhook HMAC Secret**.

The receiver accepts **either** scheme:

1. **Android SMS Gateway app** (recommended) — the app sends:
   - `X-Signature` = `HMAC-SHA256(secret, raw_body + X-Timestamp)` (hex)
   - `X-Timestamp` = unix seconds
   Freshness window: `now - 900s ≤ ts ≤ now + 60s`. Keep device clocks in sync, or signed webhooks will be rejected.
2. **Legacy** — `X-Webhook-Signature` = `HMAC-SHA256(secret, raw_body)` (hex)

> **Multi-device:** the signing key is per-device. With more than one phone, set the same signing key on all of them, or leave `Webhook HMAC Secret` empty (verification is skipped; idempotency still dedupes replays).

---

## SMS Bulk Message

Navigate to: **SMS Relay → SMS Bulk Message → New**

### Creating a Bulk Campaign

1. Choose message type: **Text** (direct message) or **Template** (use SMS Template)
2. Enter message or select template
3. Add recipients via:
   - **CSV Upload**: Drag-and-drop CSV with `phone` and optional `name` columns
   - **Recipient List**: Select a saved SMS Recipient List
4. Optionally schedule for later
5. Click **Start Sending**

### CSV Format

```csv
phone,name
+1234567890,John Doe
+0987654321,Jane Smith
```

---

## Caching

- Gateway settings cached for 300 seconds
- Opt-out list cached for 600 seconds
- Round-robin counter cached per-cycle
- Notification map cached in `sms_notification_map` key
- JWT access tokens cached per device (`sms_relay_jwt_{device}`) and reused until near expiry
