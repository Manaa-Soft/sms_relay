# Architecture

## System Overview

The `sms_relay` Frappe app bridges ERPNext business documents to physical Android phones for SMS delivery. It follows this pipeline:

**ERPNext → sms_relay hooks → SMS Queue → Device Selection → Android Phone Gateway → Webhook delivery receipts**

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│   ERPNext   │───▶│  sms_relay   │───▶│  SMS Queue   │───▶│   Device    │───▶│   Android    │
│  (Invoice,  │    │   Hooks      │    │  (async)     │    │  Selector   │    │    Phone     │
│  Payment)   │    │              │    │              │    │             │    │              │
└─────────────┘    └──────────────┘    └──────────────┘    └─────────────┘    └──────┬───────┘
                                                                                      │
                                                                                      ▼
                                                                                ┌──────────────┐
                                                                                │   Webhook    │
                                                                                │  (delivery)  │
                                                                                └──────────────┘
```

## Data Flow

### Outgoing SMS Flow (Step by Step)

1. User submits Sales Invoice / Payment Entry / Payment Request in ERPNext
2. Frappe fires `doc_events` hook → calls handler (e.g. `on_invoice_submit`)
3. Handler checks: config enabled? → gets customer phone → checks opt-out
4. Handler renders Jinja template with document context
5. Handler calls `_enqueue_sms()` → creates SMS Queue entry (status: Queued)
6. Every minute, `process_sms_queue()` scheduler job picks up queued entries
7. For each entry: `_select_device()` picks best device (priority + health + quota + throttle)
8. `_send_to_device()` makes HTTP POST to Android SMS Gateway server
9. Phone picks up the message and sends via SIM card
10. SMS Log updated with status and gateway message_id

### Delivery Receipt Flow

1. Android phone sends delivery status to webhook URL
2. `incoming_webhook()` receives the POST
3. Validates HMAC signature (if configured)
4. Updates SMS Queue and SMS Log status (Sent/Delivered/Failed)

## Module Architecture

### Module Dependency Graph

```
sms_engine.py  ← handlers.py, tasks.py, api.py, webhook_receiver.py, setup.py
    ↑
    └── Core: phone utils, device selection, gateway HTTP, queue creation, logging, throttle, templates
```

### sms_engine.py (Core Engine)

- `send_sms()` / `send_sms_override()` — Frappe hook entry points
- `_select_device()` — priority + quota + heartbeat + throttle filtering
- `_send_to_device()` — HTTP POST to gateway server
- `_clean_phone()` — E.164 normalization
- `_get_customer_phone()` — Contact chain lookup
- `_enqueue_sms()` — Queue entry creation
- `_log_sms()` — Audit trail creation
- `_check_opt_out()` — Opt-out table lookup
- `_throttle_check()` — Cache-based rate limiting
- `_render_template()` — Jinja2 rendering
- `_get_gateway_config()` — Cached settings reader

### handlers.py (Document Events)

- `on_invoice_submit()` — Sales Invoice → SMS
- `on_payment_submit()` — Payment Entry → SMS
- `on_payment_request_submit()` — Payment Request → SMS
- `_get_supplier_phone()` — Supplier contact lookup
- `_clean_phone_from_party()` — Generic party lookup

### tasks.py (Scheduled Jobs)

- `process_sms_queue()` — Every minute, dispatch queued SMS
- `send_balance_reminders()` — Daily, overdue invoice reminders
- `retry_failed_sms()` — Daily, re-enqueue failed SMS
- `cleanup_old_logs()` — Daily, delete old logs
- `reset_daily_quotas()` — Daily, reset device counters

### webhook_receiver.py (Delivery Receipts)

- `incoming_webhook()` — Public endpoint for device callbacks
- `_handle_delivered()` / `_handle_failed()` / `_handle_sent()` / `_handle_heartbeat()`

### api.py (RPC Methods)

- `send_sms_now()` — Immediate send (bypasses queue)
- `send_bulk_sms()` — Bulk enqueue from CSV
- `get_device_health()` — Device status
- `preview_template()` — Template rendering preview
- `retry_sms()` — Manual retry
- `get_sms_stats()` — Today's statistics

### setup.py (Installation)

- `after_install()` — Creates default settings and templates

## DocTypes

### SMS Gateway Settings (Singleton)

Global configuration. Controls all aspects of SMS sending.

### SMS Device

Registered Android phone. Tracks priority, quota, heartbeat, online status.

### SMS Template

Jinja2 message templates. One per notification event.

### SMS Queue

Async message queue. Status: Queued → Sending → Sent/Delivered/Failed.

### SMS Log

Audit trail. Every SMS recorded with full metadata and delivery status.

## Scheduler Jobs

| Frequency | Job | What it does |
|---|---|---|
| Every minute | process_sms_queue | Dispatch queued SMS to devices |
| Daily | send_balance_reminders | Overdue invoice notifications |
| Daily | retry_failed_sms | Re-enqueue failed SMS |
| Daily | cleanup_old_logs | Delete logs older than retention |
| Daily | reset_daily_quotas | Reset device sent_today counters |

## Error Handling

- Gateway connection failures → logged, SMS re-queued for retry
- Device offline → next device tried (failover)
- Quota exhausted → device skipped
- Throttle exceeded → device skipped
- Max retries exceeded → SMS marked Failed permanently
- Template render error → fallback to plain text default message
