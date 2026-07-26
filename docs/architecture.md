# Architecture

## System Overview

The `sms_relay` Frappe app bridges ERPNext business documents to physical Android phones (or custom HTTP SMS APIs) for SMS delivery.

```
ERPNext ──▶ hooks.py ──▶ notification_handler ──▶ SMS Queue ──▶ sms_engine ──▶ Gateway ──▶ Phone
                                                                                │
                                                                          webhook_receiver ◀── Delivery receipts
```

## Module Structure

```
sms_relay/sms_relay/
├── core/
│   ├── sms_engine.py           # Device selection, load balancing, gateway dispatch
│   ├── notification_handler.py # Doc-event trigger listener & Jinja renderer
│   ├── bulk_engine.py          # Batch processor & background worker queuing
│   └── sms_utils.py            # Phone formatting (E.164), character counters, HMAC
├── api/
│   ├── webhook_receiver.py     # Incoming SMS & delivery status webhook
│   └── endpoints.py            # REST APIs for external gateway sync
├── utils/
│   ├── jinja_methods.py        # Custom Jinja filters (money, date, clean phone)
│   ├── contact_manager.py      # Auto-linking inbound SMS to Leads/Contacts/Customers
│   └── notification_handler.py # Doc-event dispatch bridge
├── doctype/
│   ├── sms_device/             # Connection, status, quotas, Connect Device button
│   ├── sms_gateway_settings/   # Routing, rate limit, webhook secret, failover
│   ├── sms_log/                # Delivery status, timing, error details
│   ├── sms_queue/              # Priority tiers, target SIM, retry counts
│   ├── sms_template/           # Language, header/footer, char counter
│   ├── sms_opt_out/            # STOP blacklist
│   ├── sms_bulk_message/       # Campaign manager
│   ├── sms_bulk_recipient/     # Child table
│   ├── sms_notification/       # Doc-triggered rules
│   ├── sms_notification_log/   # Audit log
│   ├── sms_outbox/             # Async retry outbox
│   ├── sms_recipient_list/     # Saved groups
│   ├── sms_recipient/          # Child table
│   └── sms_message_field/      # Dynamic field mapping
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
2. Frappe fires `doc_events` hook → `notification_handler.on_doc_event()`
3. Handler loads matching SMS Notification records for the DocType
4. For each notification: check event match → evaluate condition → resolve phone → render Jinja template
5. If valid: create SMS Queue entry (priority: High if payment/OTP, Normal otherwise)
6. Every minute, `process_sms_queue()` picks up queued entries
7. `sms_engine._select_device()` picks best device (routing strategy + quota + throttle)
8. `_send_to_device()` makes HTTP POST to gateway with Basic Auth (`username:password`)
9. Gateway returns 202 Accepted → Phone app picks up message and sends via SIM
10. `sms_log` updated with status and `gateway_message_id`

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
3. HMAC signature verified (if configured)
4. Idempotency check via cache
5. SMS Queue and SMS Log status updated
6. If incoming SMS: Communication doc created, auto-linked to Contact/Lead

## Core Modules

### sms_engine.py

| Function | Purpose |
|---|---|
| `send_sms()` | Main entry point, hooks into Frappe |
| `send_sms_override()` | Monkey-patches Frappe SMS Settings |
| `_select_device()` | Round Robin / Priority / Random routing |
| `_check_quota()` | Daily quota check per device |
| `_throttle_check()` | Per-device per-minute rate limit |
| `_send_to_device()` | HTTP POST to gateway (reads api_path/timeout from settings, accepts 202) |
| `_enqueue_sms()` | Create SMS Queue entry |
| `_log_sms()` | Create SMS Log entry |
| `_render_template()` | Jinja2 template rendering |

### notification_handler.py

| Function | Purpose |
|---|---|
| `on_doc_event()` | Generic dispatcher for all doc_events |
| `_should_send()` | Evaluate Python condition via safe_eval |
| `_render_notification()` | Render Jinja template with doc context |
| `_get_phone_number()` | Resolve phone from field or Contact chain |
| `_send_notification_sms()` | Create queue entry with priority |
| `_log_notification()` | Write SMS Notification Log |

### bulk_engine.py

| Function | Purpose |
|---|---|
| `create_bulk_job()` | Create bulk message with CSV recipients |
| `create_bulk_from_recipient_list()` | Load from saved Recipient List |
| `process_bulk_job()` | Send batch of pending recipients |
| `cancel_bulk_job()` | Cancel processing |

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
| Every minute | `process_outbox` | Process outbox with exponential backoff |
| Every minute | `process_bulk_messages` | Process bulk campaign batches |
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
