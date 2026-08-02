# Architecture

## System Overview

The `sms_relay` Frappe app bridges ERPNext business documents to physical Android phones (or custom HTTP SMS APIs) for SMS delivery.

```
ERPNext ──▶ hooks.py ["*"] ──▶ utils/__init__.py ──▶ SMS Notification ──▶ SMS Queue ──▶ sms_engine ──▶ Docker Server ──▶ Phone
                                                                                          │
                                                                                    webhook_receiver ◀── Delivery receipts
```

## Authentication

The system uses a two-layer authentication model between three components:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Frappe/ERPNext ──── Basic Auth ────▶ Docker Server                          │
│                                       (port 8085)                           │
│                                                                             │
│ POST /api/3rdparty/v1/message                                               │
│ Authorization: Basic base64(login:password)                                 │
│                                                                             │
│ Credentials come from the SMS Device record (username/password).            │
│ These are the same login:password the phone received during registration.   │
│ The server validates against its MySQL database (bcrypt).                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ Phone App ──── Bearer Token ────▶ Docker Server                             │
│                                     (port 8085)                             │
│                                                                             │
│ Device Registration:                                                        │
│   POST /api/mobile/v1/device                                                │
│   Auth: Bearer <private_token> (private mode) or Basic Auth                 │
│   Response: { login, password, token, id }                                  │
│                                                                             │
│ Message Polling:                                                            │
│   GET /api/mobile/v1/message                                                │
│   Auth: Bearer <device_token>                                               │
│                                                                             │
│ The phone stores login/password for display — Frappe uses these for SMS.   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key points:**
- Basic Auth and JWT Bearer are **alternatives** for `/api/3rdparty/v1/message`, not combined
- The `private_token` lives in the Docker server's `config.yml` — it secures device registration, not message sending
- Frappe never sends Bearer tokens to the server — it always uses Basic Auth

## Module Structure

```
sms_relay/sms_relay/
├── core/
│   ├── sms_engine.py           # Device selection, load balancing, gateway dispatch, cancel, idempotency
│   ├── notification_handler.py # Doc-event trigger listener & Jinja renderer
│   ├── bulk_engine.py          # Batch processor & background worker queuing
│   └── sms_utils.py            # Phone formatting (E.164), character counters, HMAC
├── api/
│   ├── webhook_receiver.py     # Incoming SMS, delivery status, cancellation, webhook retry queue
│   └── endpoints.py            # REST APIs: send, bulk, health, cancel, history, inbox, settings
├── utils/
│   ├── __init__.py             # Notification map, after_commit dispatch, scheduler triggers
│   ├── jinja_methods.py        # Custom Jinja filters (money, date, clean phone)
│   └── contact_manager.py      # Auto-linking inbound SMS to Leads/Contacts/Customers
├── doctype/
│   ├── sms_device/             # Connection, status, quotas, Connect Device button
│   ├── sms_gateway_settings/   # Routing, rate limit, webhook secret, failover, send intervals
│   ├── sms_log/                # Delivery status, timing, error details, device_id, message_id
│   ├── sms_queue/              # Priority tiers, target SIM, retry counts, TTL, idempotency
│   ├── sms_template/           # Language, header/footer, char counter
│   ├── sms_opt_out/            # STOP blacklist
│   ├── sms_bulk_message/       # Campaign manager
│   ├── sms_bulk_recipient/     # Child table
│   ├── sms_notification/       # Doc-triggered rules (Jinja or Parameter template type)
│   ├── sms_notification_log/   # Audit log
│   ├── sms_outbox/             # Async retry outbox
│   ├── sms_webhook_delivery/   # Webhook retry queue with exponential backoff
│   ├── sms_recipient_list/     # Saved groups
│   ├── sms_recipient/          # Child table
│   └── sms_message_field/      # Positional parameter mapping for {{N}}
├── public/js/
│   ├── sms_dashboard.js        # Real-time device health & stats
│   ├── bulk_message.js         # CSV upload, progress bar, char counter
│   └── notification_builder.js # Test/preview dialogs
├── hooks.py
├── tasks.py
└── setup.py
```

## Data Flow

### Outgoing SMS

1. User submits Sales Invoice / Payment Request / Delivery Note / Purchase Order in ERPNext
2. Frappe fires `doc_events` hook → `utils/__init__.py` `run_server_script_for_doc_event()`
3. Handler looks up matching SMS Notification records from cached notification map
4. For each notification: check event match → evaluate condition → resolve phone → render message
5. If valid: create SMS Queue entry (priority: High if payment/OTP, Normal otherwise)
6. Every minute, `process_sms_queue()` picks up queued entries
7. `sms_engine._select_device()` picks best device (routing strategy + quota + throttle)
8. `_send_to_device()` makes HTTP POST to Docker server with Basic Auth (`username:password`)
9. Docker server returns 202 Accepted → Phone app picks up message and sends via SIM
10. `sms_log` updated with status and `gateway_message_id`

### Message Rendering

**Jinja mode** (`template_type == "Jinja"`):
- Template body rendered via Jinja2 with `doc` context
- Positional params `{{1}}`, `{{2}}` are also replaced from Fields table before Jinja rendering
- Full access to document fields, filters, conditionals

**Parameter mode** (`template_type == "Parameter"`):
- Template body rendered by `_replace_positional_params()` only (no Jinja2)
- `{{1}}`, `{{2}}` etc. replaced with values from the Fields child table
- Fields table is visible; each row maps a position to a DocType field name

### Bulk SMS

1. User creates SMS Bulk Message with CSV or recipient list
2. Status set to "Draft", recipients loaded into child table
3. On "Start Sending" or scheduler: status → "Processing"
4. `bulk_engine.process_bulk_job()` sends batch of 10 per cycle
5. Each recipient checked against opt-out, message resolved (text or template)
6. SMS Queue entry created per recipient
7. Standard queue processing takes over

### Delivery Receipt

1. Android phone sends delivery status to webhook URL
2. `webhook_receiver.incoming_webhook()` receives POST
3. HMAC signature verified if configured — accepts either `X-Webhook-Signature` (legacy, HMAC over raw body) or `X-Signature` + `X-Timestamp` (app scheme, HMAC over body + timestamp with 15-min freshness window)
4. Idempotency check via cache
5. SMS Queue and SMS Log status updated
6. If `sms:cancelled`: both Queue and Log marked as Cancelled
7. If incoming SMS (`sms:received`/`sms:data-received`/`mms:received`/`mms:downloaded`): Communication doc created, auto-linked to Contact/Lead
8. If `app:started`: matching SMS Device heartbeat and SIM info refreshed
9. If webhook delivery fails: `SMS Webhook Delivery` entry created for retry

## Core Modules

### sms_engine.py

| Function | Purpose |
|---|---|
| `send_sms()` | Main entry point, hooks into Frappe |
| `send_sms_override()` | Monkey-patches Frappe SMS Settings |
| `cancel_message()` | Cancel a queued SMS before sending |
| `_select_device()` | Round Robin / Priority / Random routing |
| `_check_quota()` | Daily quota check per device |
| `_throttle_check()` | Per-device per-minute rate limit |
| `_send_to_device()` | HTTP POST to gateway (Basic Auth, accepts 202) |
| `_send_android_gateway()` | Android SMS Gateway payload with idempotency check |
| `_send_custom_http()` | Custom HTTP API with Bearer token |
| `_enqueue_sms()` | Create SMS Queue entry (supports TTL, scheduling) |
| `_log_sms()` | Create SMS Log entry (supports message_id, device_id) |
| `_render_template()` | Jinja2 template rendering |

### utils/__init__.py

| Function | Purpose |
|---|---|
| `run_server_script_for_doc_event()` | Entry point for `doc_events["*"]` |
| `get_notifications_map()` | Build/cache `{doctype: {event: [names]}}` map |
| `_schedule_sms_notification()` | Schedule notification after commit |
| `_send_sms_notification()` | Send SMS notification for a doc event |
| `trigger_sms_notifications()` | Run scheduler-based notifications |

### tasks.py

| Function | Purpose |
|---|---|
| `process_sms_queue()` | Dispatch queued SMS to devices (every minute) |
| `process_scheduled_messages()` | Process deferred/future-scheduled SMS (every minute) |
| `process_outbox()` | Process outbox with exponential backoff (every minute) |
| `process_bulk_messages()` | Process bulk campaigns in batches (every minute) |
| `process_webhook_deliveries()` | Retry failed webhooks with exponential backoff (every minute) |
| `check_device_health()` | Heartbeat, battery, signal checks (hourly) |
| `send_overdue_reminders()` | Overdue invoice notifications (daily) |
| `retry_failed_sms()` | Re-enqueue retryable failures (daily) |
| `cleanup_old_logs()` | Purge old SMS Log entries (daily, 90-day retention) |
| `reset_daily_quotas()` | Reset device daily counters (daily) |

### sms_utils.py

| Function | Purpose |
|---|---|
| `clean_phone()` | E.164 normalization |
| `count_sms_parts()` | GSM-7/Unicode detection + segment count |
| `verify_webhook_signature()` | HMAC-SHA256 verification |
| `is_opted_out()` | Check opt-out blacklist |
| `get_relay_settings()` | Cached settings loader |

## Scheduler Jobs

| Frequency | Job | Description |
|---|---|---|
| Every minute | `process_sms_queue` | Flush queued SMS to devices |
| Every minute | `process_scheduled_messages` | Process deferred/future-scheduled SMS |
| Every minute | `process_outbox` | Process outbox with exponential backoff |
| Every minute | `process_bulk_messages` | Process bulk campaign batches |
| Every minute | `process_webhook_deliveries` | Retry failed webhooks with backoff |
| Hourly | `check_device_health` | Heartbeat, battery, signal checks |
| Daily | `send_overdue_reminders` | Overdue invoice notifications |
| Daily | `retry_failed_sms` | Re-enqueue retryable failures |
| Daily | `cleanup_old_logs` | Purge old SMS Log entries |
| Daily | `reset_daily_quotas` | Reset device daily counters |

## Error Handling

- Gateway connection failure → logged, SMS re-queued for retry
- Device offline → next device tried (failover if enabled)
- Quota exhausted → device skipped, try next
- Throttle exceeded → device skipped for this cycle
- Max retries exceeded → SMS marked Failed permanently
- Template render error → logged, notification skipped
- Opt-out detected → SMS silently skipped
- HMAC verification failure → webhook rejected
- Missing device credentials → clear error message returned
