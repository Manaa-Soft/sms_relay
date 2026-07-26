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

## check_device_health

**Frequency:** Hourly

**Purpose:** Checks device heartbeat, battery status, and signal strength.

**What it does:**
1. For each enabled device (`is_active = 1`):
   a. GET request to `{server_url}/api/mobile/v1/device` with Basic Auth
   b. Update battery_level, signal_strength
   c. If unreachable → set is_online = 0

---

## send_overdue_reminders

**Frequency:** Daily

**Purpose:** Sends overdue invoice payment reminder SMS.

**What it does:**
1. Fetches submitted Sales Invoices with outstanding > 0 and due_date < today
2. For each invoice:
   a. Gets customer phone from Contact chain
   b. Checks opt-out list
   c. Creates queue entry with message: "Dear {customer}, invoice {name} of {amount} is overdue (due {date}). Outstanding: {outstanding}. Please pay soon."
3. Commits changes

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
        "sms_relay.tasks.process_outbox",
        "sms_relay.tasks.process_bulk_messages",
        "sms_relay.utils.trigger_sms_notifications_all",
    ],
    "hourly": [
        "sms_relay.tasks.check_device_health",
        "sms_relay.utils.trigger_sms_notifications_hourly",
    ],
    "daily": [
        "sms_relay.tasks.send_overdue_reminders",
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
