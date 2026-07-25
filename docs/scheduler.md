# Scheduler Jobs

sms_relay registers several jobs with the Frappe scheduler. These run automatically at their configured frequencies.

## process_sms_queue

**Frequency:** Every minute (`"all"` scheduler event)

**Purpose:** Dispatches queued SMS messages to available devices.

**What it does:**
1. Checks if SMS relay is enabled in Gateway Settings
2. Fetches up to `batch_size` (default: 10) SMS Queue entries with status "Queued"
3. Orders by priority ASC (lowest first), then creation ASC (oldest first)
4. For each entry:
   a. Sets status to "Sending"
   b. Calls `_select_device()` to find best available device
   c. If no device available → sets back to "Queued" (tried next cycle)
   d. Calls `_send_to_device()` → HTTP POST to gateway server
   e. On success: sets status to "Sent", records gateway message_id, increments device counter, creates SMS Log
   f. On failure: increments retry_count. If < max_retries → sets back to "Queued". If >= max_retries → sets to "Failed"
5. Commits all database changes

**Config values read:** `enabled`, `max_retry_count`

**Side effects:**
- Updates SMS Queue status
- Updates SMS Device sent_today counter
- Creates SMS Log entries
- May log errors to Frappe error log

---

## send_balance_reminders

**Frequency:** Daily

**Purpose:** Sends overdue invoice payment reminder SMS to customers.

**What it does:**
1. Checks if enabled and `send_overdue_reminders` is on
2. Parses `reminder_intervals` (e.g. "7,14,30,60,90") into a list of integers
3. Fetches all overdue Sales Invoices (status=Overdue, outstanding > 0, submitted)
4. Groups invoices by customer
5. For each customer:
   a. Finds earliest due date across their invoices
   b. Calculates days_overdue from today
   c. Checks if days_overdue matches any configured interval
   d. If match → gets customer phone, checks opt-out
   e. Calculates total outstanding across all overdue invoices
   f. Renders template or uses default message
   g. Enqueues SMS with priority 3 (low)
6. Commits all database changes

**Config values read:** `enabled`, `send_overdue_reminders`, `reminder_intervals`, `overdue_template`

**Side effects:**
- Creates SMS Queue entries
- Groups by customer to prevent duplicate reminders on the same day

**Example flow:**
- Today: 2026-07-26
- Invoice SINV-001: due_date=2026-07-19, outstanding=5000
- Invoice SINV-002: due_date=2026-07-12, outstanding=3000
- Both for customer "ABC Corp"
- Earliest due: 2026-07-12 → days_overdue = 14
- Interval 14 matches → sends reminder for both invoices (total: 8000)

---

## retry_failed_sms

**Frequency:** Daily

**Purpose:** Re-enqueues SMS that failed but haven't exhausted retry attempts.

**What it does:**
1. Fetches SMS Queue entries where status="Failed" AND retry_count < max_retries
2. Sets status back to "Queued" for each
3. Logs the count of re-enqueued entries
4. Commits changes

**Config values read:** `max_retry_count`

**Side effects:**
- Changes SMS Queue status from "Failed" to "Queued"

---

## cleanup_old_logs

**Frequency:** Daily

**Purpose:** Deletes SMS Log entries older than the configured retention period.

**What it does:**
1. Calculates cutoff date: today - `log_retention` days (default: 90)
2. Deletes all SMS Log entries created before cutoff
3. Logs the cleanup action

**Config values read:** `log_retention` (days)

**Side effects:**
- Permanent deletion of old SMS Log records

**Note:** This is irreversible. Adjust `log_retention` in SMS Gateway Settings if you need longer history.

---

## reset_daily_quotas

**Frequency:** Daily

**Purpose:** Resets the `sent_today` counter on all SMS Devices.

**What it does:**
1. Runs `UPDATE tabSMS Device SET sent_today = 0`
2. Commits changes
3. Logs the reset action

**Side effects:**
- All devices get fresh daily quotas

## Scheduler Configuration

Frappe's scheduler runs these jobs based on their registration in `hooks.py`:

```python
scheduler_events = {
    "all": [
        "sms_relay.tasks.process_sms_queue",      # Every ~3 minutes (Frappe "all" interval)
    ],
    "daily": [
        "sms_relay.tasks.send_balance_reminders",  # Once per day
        "sms_relay.tasks.retry_failed_sms",        # Once per day
        "sms_relay.tasks.cleanup_old_logs",        # Once per day
        "sms_relay.tasks.reset_daily_quotas",      # Once per day
    ],
}
```

**Note:** The `"all"` scheduler event in Frappe runs approximately every 3 minutes (not every minute as the name might suggest). If you need more frequent processing, consider using `hooks.py` with `"all"` plus a custom scheduler, or use `frappe.enqueue` with a longer-running worker.

## Monitoring

- Check **SMS Queue** list for entries with status "Failed" (need attention)
- Check **SMS Log** list for delivery status history
- Check Frappe **Error Log** for scheduler errors
- Use `sms_relay.api.get_sms_stats` for daily statistics
