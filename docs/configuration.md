# Configuration Guide

## SMS Gateway Settings

Navigate to: **SMS Relay → SMS Gateway Settings**

Singleton DocType — one record for the entire site.

### Gateway

| Field | Type | Default | Description |
|---|---|---|---|
| Enabled | Check | 1 | Master toggle. When off, no SMS is sent. |
| Server URL | Data | — | Gateway server URL (e.g. `http://192.168.1.15:8085`). |
| API Path | Data | /api/3rdparty/v1/message | API endpoint path. |
| Private Token | Password | — | Bearer token for server-level auth. Overrides device username/password. |
| Timeout | Int | 15 | HTTP timeout in seconds. |
| Max Retry Count | Int | 3 | Default retry attempts for failed sends. |

### Routing & Rate Limiting

| Field | Type | Default | Description |
|---|---|---|---|
| Routing Strategy | Select | Round Robin | How to select among multiple devices. |
| Enable Failover | Check | 1 | Try next device if primary fails. |
| Global Rate Limit | Int | 60 | Max SMS per minute across all devices. |
| Check Opt-Out | Check | 1 | Skip opted-out numbers before sending. |

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
| Webhook HMAC Secret | Password | — | Secret for verifying webhook signatures. |

---

## SMS Device

Navigate to: **SMS Relay → SMS Device → New**

Each Android phone or HTTP SMS API endpoint is a separate Device record.

### Connection

| Field | Type | Required | Description |
|---|---|---|---|
| Device Name | Data | Yes | Human-readable label (e.g. "Office Phone"). |
| Device ID | Data | No | Unique ID from the phone app. Filled by Connect Device. |
| Mode | Select | Yes | Android SMS Gateway / Custom HTTP API. |
| Server URL | Data | Yes | Gateway server URL for this device (e.g. `http://192.168.1.15:8085`). |
| Username | Data | No | Gateway auth username. |
| Password | Password | No | Gateway auth password. |
| SIM Number | Select | No | SIM slot 1 or 2. |
| Priority | Int | No | Lower = higher priority. |
| Active | Check | Yes | Enable/disable device. |

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
| Daily Quota | Int | 5000 | Max SMS per day. Resets daily. |
| Sent Today | Int | 0 | Current day count (read-only). |
| Hourly Quota | Int | 500 | Max SMS per hour. |

### Connect Device Button

Click **Connect Device** in the form to auto-fetch device info from the gateway:
- Queries `GET {server_url}/api/mobile/v1/device` for device details
- Queries `GET {server_url}/health` for online status
- Auto-fills: `device_id`, `device_model`, `carrier_name`, `sim_phone_number`, `app_version`, `battery_level`

### Send Test SMS Button

Click **Send Test SMS** to send a test message through this device.

---

## SMS Template

Navigate to: **SMS Relay → SMS Template → New**

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| Template Name | Data | Yes | Unique name. |
| Event | Select | Yes | Event type. |
| Language | Link: Language | No | Template language. |
| Header | Small Text | No | Prepended to every message. |
| Message Template | Code | Yes | Jinja2 body. |
| Footer | Small Text | No | Appended to every message. |

### Template Variables

All templates have access to `{{ doc }}` (the full document) and `{{ frappe }}`:

```
Dear {{ doc.customer }}, your invoice {{ doc.name }} for {{ frappe.utils.fmt_money(doc.grand_total) }} is due on {{ doc.due_date }}.
```

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
| Notification Type | Select | Yes | DocType notification / SMS Alert / WhatsApp Message. |
| Disabled | Check | No | Disable this rule. |
| Reference DocType | Link: DocType | Yes | Target DocType (Sales Invoice, etc.). |
| DocType Event | Select | Yes | On Submit / On Save / On Validate / On Payment / On Cancel / On TRASH. |
| Field Name | Data | Yes | Field containing phone number. |
| Message Template | Code (Jinja) | Yes | Jinja2 message body. |
| Condition | Code (Python) | No | `return True` to send. |
| Event Frequency | Select | No | How often to trigger (for scheduled notifications). |

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

### In SMS Gateway Server (config.yml)

```yaml
server:
  webhooks:
    - url: "http://YOUR-FRAPPE-SITE/api/method/sms_relay.api.webhook_receiver.incoming_webhook"
      events:
        - sms:delivered
        - sms:failed
        - sms:received
        - system:ping
```

### HMAC Signature Verification

If `Webhook HMAC Secret` is configured:

1. Device computes `HMAC-SHA256(secret, payload)`
2. Sends signature in `X-Webhook-Signature` header
3. Server verifies before processing

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
