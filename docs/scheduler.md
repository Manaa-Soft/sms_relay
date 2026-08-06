# Scheduler Jobs

sms_relay registers jobs with the Frappe scheduler. These run automatically at their configured frequencies.

## process_sms_queue

**Frequency:** Every minute (`"all"` scheduler event)

**Purpose:** Dispatches queued SMS messages to available devices.

**What it does:**
1. Fetches up to 50 SMS Queue entries with status "Queued"
2. Orders by creation ASC (oldest first)
3. For each entry:
   a. Validates phone number
   b. Selects device via routing strategy (Round Robin / Priority / Random)
   c. Checks per-minute rate limit
   d. HTTP POST to Docker server with Basic Auth (`username:password` from SMS Device)
   e. On success (HTTP 200/201/202): status → "Sent", creates SMS Log entry
   f. On failure: increments retry_count. If < max_retries → status stays "Queued" with backoff. If >= max_retries → status → "Failed"
4. Commits all database changes

---

## process_scheduled_messages

**Frequency:** Every minute (`"all"` scheduler event)

**Purpose:** Processes deferred/future-scheduled SMS messages that are now due.

**What it does:**
1. Fetches SMS Queue entries with status "Queued", `scheduled_at <= now()`, and `scheduled_at` is set
2. Orders by scheduled_at ASC
3. For each entry: delegates to `_process_queue_item()` (same as process_sms_queue)
4. Commits changes

---

## process_outbox

**Frequency:** Every minute

**Purpose:** Processes the SMS Outbox with exponential backoff retry.

**What it does:**
1. Fetches Outbox entries with status "Pending" or "Failed" and `next_retry_at <= now()`
2. For each entry:
   a. Checks max attempts not exceeded
   b. Selects device, checks rate limit
   c. Sends via gateway with Basic Auth
   d. On success: status → "Sent"
   e. On failure: increments attempts, calculates next retry (2^attempts minutes)
   f. If max attempts exceeded: status → "Failed"
3. Commits changes

**Backoff Schedule:**
| Attempt | Wait Before Next |
|---|---|
| 1 | 1 minute |
| 2 | 2 minutes |
| 3 | 4 minutes |
| 4 | 8 minutes |
| 5 | 16 minutes |

---

## process_bulk_messages

**Frequency:** Every minute

**Purpose:** Processes bulk SMS campaigns in batches.

**What it does:**
1. Finds Bulk Messages with status "Draft" or "Processing"
2. For each bulk:
   a. If Draft → set status to "Processing", record start time
   b. Take next 10 pending recipients
   c. For each: check opt-out, resolve message, create queue entry
   d. Update sent/failed/pending counts
   e. If no pending recipients → set status to "Completed"
3. Commits changes

---

## process_webhook_deliveries

**Frequency:** Every minute (`"all"` scheduler event)

**Purpose:** Retries failed webhook deliveries with exponential backoff.

**What it does:**
1. Fetches SMS Webhook Delivery entries with status "Pending" or "Failed" and `next_retry_at <= now()`
2. For each entry:
   a. Checks max attempts not exceeded
   b. Sends HTTP POST to the webhook URL with payload and headers
   c. On success (2xx): status → "Sent"
   d. On failure: increments attempts, calculates next retry (base_delay * 2^attempts)
   e. If max attempts exceeded: status → "Failed"
3. Commits changes

**Backoff Schedule:**
| Attempt | Wait Before Next |
|---|---|
| 1 | 30 seconds |
| 2 | 1 minute |
| 3 | 2 minutes |
| 4 | 4 minutes |
| 5 | 8 minutes |
| ... | Doubles each time |

---

## check_device_health

**Frequency:** Hourly

**Purpose:** Checks device heartbeat, battery status, and signal strength.

**What it does:**
1. For each enabled device (`is_active = 1`):
   a. GET request to `{server_url}/api/mobile/v1/device` with Basic Auth
   b. Update battery_level, signal_strength
   c. If unreachable → set is_online = 0

---

## sync_delivery_status

**Frequency:** Hourly (skipped when **Enable Delivery Status Sync** is off)

**Purpose:** Delivery-status reconciliation fallback for messages whose terminal webhook was never received (e.g. the site was down when the report fired).

**What it does:**
1. Finds SMS Queue entries with status "Sent", a `gateway_message_id`, and `modified` older than **Status Sync Age (minutes)** (default 30)
2. For each: `GET /messages/{id}` (fallback `/message/{id}`) via the device's gateway client
3. Maps the gateway `ProcessingState` to SMS Relay status:
   - `Processed`/`Sent` → Sent
   - `Delivered` → Delivered (sets `delivery_status` + `delivered_at`)
   - `Failed` → Failed (captures per-recipient error into `SMS Log.error_message`)
   - `Cancelled`/`Cancelling` → Cancelled
4. Updates the SMS Queue row and every SMS Log row sharing the `gateway_message_id`
5. Commits changes

---

## sync_device_inbox

**Frequency:** Hourly (skipped when **Enable Inbox Sync** is off)

**Purpose:** Backfill incoming SMS from the device's stored inbox so messages that arrived while the site was unreachable are not lost.

**What it does:**
1. For each active Android SMS Gateway device: `GET /inbox` (up to 100 messages)
2. Skips messages already imported (deduped by gateway inbox message id)
3. Creates an SMS Queue entry per message with status **Received**, `recipient` = sender, `message` = content preview, `sim_number` from the message
4. Commits changes

Messages are also imported in real time via `sms:received` webhooks; the inbox sweep is only a safety net.

---

## Send Overdue Invoice Reminders (seeded SMS Notification)

**Trigger:** Sales Invoice → **After Submit** (DocType Event)

**Purpose:** Sends an overdue invoice payment reminder SMS when a Sales Invoice is submitted. No hardcoded job — it ships as a **seeded SMS Notification** + **SMS Templates**, created automatically on install/migrate, so it can be stopped (tick **Disabled**) or edited from the desk.

**What it does:**
1. Fires when a Sales Invoice is submitted (`notification_type = DocType Event`, `doctype_event = After Submit`)
2. Evaluates the **Condition (Python Expression)**: the default gate sends only when the invoice has an unpaid balance **and** is past its due date
   ```python
   (doc.outstanding_amount or 0) > 0 and doc.due_date and frappe.utils.getdate(doc.due_date) < frappe.utils.getdate()
   ```
   Fully paid or not-yet-due invoices are skipped.
3. Reads the recipient phone from the invoice's **`contact_mobile`** field (auto-filled from the customer's primary Contact)
4. Picks the template by language: invoice or Customer `language` = Arabic → **"Overdue Invoice Reminder (Arabic)"**, otherwise → **"Overdue Invoice Reminder"**
5. Renders the Jinja template against the invoice and enqueues one SMS
6. Disable the notification to stop the reminders; edit the templates or the condition to change behaviour

> The legacy daily scan (Scheduler Event + `Overdue Invoices` data source) remains available in the doctype but is no longer used by the seeded records.

**Seeded records** (idempotent, created by `after_install` / `after_migrate`):
- SMS Template **"Overdue Invoice Reminder"** (EN) and **"Overdue Invoice Reminder (Arabic)"**
- SMS Notification **"Send Overdue Invoice Reminders"** (DocType Event, Sales Invoice → After Submit, `contact_mobile`, overdue Condition, active by default)

All default templates (Payment Reminder, Order Confirmation, Dispatch Notification, Payment Link, Overdue Invoice Reminder) also ship an **"(Arabic)"** variant, auto-selected for Arabic-language recipients.

## Seeded Notifications (created on install / migrate)

| Notification | Type | Trigger | Template | Phone field | Default |
|---|---|---|---|---|---|
| Send Overdue Invoice Reminders | DocType Event | Sales Invoice → After Submit | Overdue Invoice Reminder | `contact_mobile` | **Enabled** |
| Send Payment Reminder | DocType Event | Sales Invoice → After Submit | Payment Reminder | `contact_mobile` | Disabled |
| Send Order Confirmation | DocType Event | Sales Order → After Submit | Order Confirmation | `contact_mobile` | Disabled |
| Send Dispatch Notification | DocType Event | Delivery Note → After Submit | Dispatch Notification | `contact_mobile` | Disabled |
| Send Payment Link | DocType Event | Sales Invoice → After Submit | Payment Link | `contact_mobile` | Disabled |

> **Phone Number Field:** Sales Order, Delivery Note and Sales Invoice all expose ERPNext's standard `contact_mobile` field (auto-filled from the customer's primary Contact). A notification sends only when that field is populated on the document.
>
> **Condition:** "Send Overdue Invoice Reminders" and "Send Payment Reminder" ship with the overdue gate above (unpaid balance + past due date) so they never fire on freshly submitted, on-time, or fully paid invoices. The upgrade fills the Condition only when the field is blank — your own expressions are never overwritten.
>
> **Language:** for DocType Event notifications the message is auto-localized — if the document (or its Customer) has an Arabic `language`, the `"(Arabic)"` template variant is used when it exists.
>
> **Upgrade:** existing installs that seeded the two reminder notifications as daily Scheduler Events are auto-converted to DocType Event (After Submit) with `contact_mobile` and the default Condition on the next `bench migrate`; your Disabled/template choices are preserved.

---

## retry_failed_sms

**Frequency:** Daily

**Purpose:** Re-enqueues SMS that failed but haven't exhausted retries.

**What it does:**
1. Finds Queue entries with status "Failed" and retry_count < max_retries
2. Sets status back to "Queued" with incremented retry_count
3. Commits changes

---

## cleanup_old_logs

**Frequency:** Daily

**Purpose:** Deletes old SMS Log entries (retention: 90 days).

**What it does:**
1. Calculates cutoff: today - 90 days
2. Deletes all SMS Log entries created before cutoff
3. Commits changes

---

## reset_daily_quotas

**Frequency:** Daily

**Purpose:** Resets daily counters on all active devices.

**What it does:**
1. Sets sent_today = 0 on all SMS Device records where `is_active = 1`
2. Commits changes

---

## Scheduler Configuration

```python
scheduler_events = {
    "all": [
        "sms_relay.tasks.process_sms_queue",
        "sms_relay.tasks.process_scheduled_messages",
        "sms_relay.tasks.process_outbox",
        "sms_relay.tasks.process_bulk_messages",
        "sms_relay.tasks.process_webhook_deliveries",
        "sms_relay.utils.trigger_sms_notifications_all",
    ],
    "hourly": [
        "sms_relay.tasks.check_device_health",
        "sms_relay.tasks.sync_delivery_status",
        "sms_relay.tasks.sync_device_inbox",
        "sms_relay.utils.trigger_sms_notifications_hourly",
    ],
    "daily": [
        "sms_relay.tasks.retry_failed_sms",
        "sms_relay.tasks.cleanup_old_logs",
        "sms_relay.tasks.reset_daily_quotas",
        "sms_relay.utils.trigger_sms_notifications_daily",
    ],
    "weekly": [
        "sms_relay.utils.trigger_sms_notifications_weekly",
    ],
    "monthly": [
        "sms_relay.utils.trigger_sms_notifications_monthly",
    ],
    "yearly": [
        "sms_relay.utils.trigger_sms_notifications_yearly",
    ],
}
```

**Note:** Frappe's `"all"` scheduler runs approximately every 1-3 minutes.

SMS Notifications with `notification_type == "Scheduler Event"` are triggered by the `trigger_sms_notifications_*` functions, which run at the frequency specified in their `event_frequency` field.

## Monitoring

- **SMS Queue** list: check for "Failed" entries needing attention
- **SMS Log** list: delivery status history
- **SMS Bulk Message** list: campaign progress
- **Error Log**: scheduler errors (search "SMS Relay")
- **SMS Dashboard**: real-time device health and stats
