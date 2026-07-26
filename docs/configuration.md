# Configuration Guide

## SMS Gateway Settings

Navigate to: **SMS Relay → SMS Gateway Settings**

Singleton DocType — one record for the entire site.

### General

| Field | Type | Default | Description |
|---|---|---|---|
| Enabled | Check | 0 | Master toggle. When off, no SMS is sent. |
| Sender Name | Data | — | Default sender label. |
| Server URL | Data | — | Global gateway server URL (e.g. `http://192.168.1.15:8080`). |
| API Path | Data | — | API endpoint path. |
| Username | Data | — | Gateway auth username. |
| Password | Password | — | Gateway auth password. |
| Private Token | Password | — | Bearer token alternative. |
| Timeout | Int | 15 | HTTP timeout seconds. |

### Routing & Failover

| Field | Type | Default | Description |
|---|---|---|---|
| Routing Strategy | Select | Round Robin | How to select among multiple devices. |
| Enable Failover | Check | 1 | Try next device if primary fails. |
| Global Rate Limit | Int | 60 | Max SMS per minute across all devices. |

### Routing Strategies

| Strategy | Behavior |
|---|---|
| Round Robin | Rotate through devices sequentially |
| Priority | Try highest-priority device first, fall through on failure |
| Random | Random device selection |

### Webhook Security

| Field | Type | Default | Description |
|---|---|---|---|
| Webhook Secret | Password | — | HMAC-SHA256 secret for verifying webhook signatures. |
| Webhook Signature Header | Data | X-Webhook-Signature | Header containing the signature. |

---

## SMS Device

Navigate to: **SMS Relay → SMS Device → New**

Each Android phone or HTTP SMS API endpoint is a separate Device record.

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| Device Name | Data | Yes | Human-readable label (e.g. "Office Phone"). |
| Gateway URL | Data | Yes | Gateway server URL for this device. |
| Gateway Type | Select | Yes | Android SMS Gateway / Custom HTTP API. |
| API Key | Password | No | Per-device authentication token. |
| Active | Check | Yes | Enable/disable device. |
| Priority | Int | No | Lower = higher priority. |
| SIM Slot | Select | No | 1 or 2. |
| Hourly Quota | Int | 500 | Max SMS per hour. |
| Daily Quota | Int | 5000 | Max SMS per day. |
| Webhook Callback URL | Data | No | Delivery report callback URL. |

### Status Fields (Read-only)

| Field | Description |
|---|---|
| Battery Level | Device battery percentage |
| Signal Strength | Network signal info |

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
| Enabled | Check | Yes | Enable/disable this rule. |
| Reference DocType | Link: DocType | Yes | Target DocType (Sales Invoice, etc.). |
| Event | Select | Yes | On Submit / On Save / On Validate. |
| SMS Account | Link: SMS Device | No | Specific device (auto-select if empty). |
| Phone Field | Data | Yes | Field name containing phone number. |
| Message Template | Code (Jinja) | Yes | Jinja2 message body. |
| Condition | Code (Python) | No | `return True` to send. |

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

1. `phone_field` value on the document
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

If `Webhook Secret` is configured:

1. Device computes `HMAC-SHA256(secret, payload)` 
2. Sends signature in the configured header (default: `X-Webhook-Signature`)
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

## Environment Variables

No environment variables required. All configuration is in the SMS Gateway Settings DocType.

## Caching

- Gateway settings cached for 300 seconds
- Opt-out list cached for 600 seconds
- Round-robin counter cached per-cycle
- Throttle counters cached per-minute
