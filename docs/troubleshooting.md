# Troubleshooting Guide

## Quick Diagnostics

### Check if SMS relay is enabled
```python
# In bench console
frappe.get_single("SMS Gateway Settings").enabled
# Should return 1
```

### Check device status
```python
# In bench console
frappe.get_all("SMS Device", fields=["name", "status", "last_heartbeat", "sent_today", "daily_quota"])
```

### Check queue status
```python
# In bench console
frappe.get_all("SMS Queue", filters={"status": "Queued"}, limit=10)
```

### Check recent SMS logs
```python
# In bench console
frappe.get_all("SMS Log", order_by="creation desc", limit=10, fields=["name", "phone", "status", "error_message"])
```

---

## Common Issues

### Phone shows "Offline" in SMS Device

**Symptoms:**
- Device status shows "Offline" or "is_online" is 0
- No SMS being sent

**Causes:**
1. Phone app not connected to server
2. Network connectivity issue
3. Server URL incorrect
4. Heartbeat not reaching Frappe

**Fixes:**
1. Open SMS Gateway app on phone → verify "Connected" status
2. Check phone can reach the server: `ping YOUR-SERVER-IP`
3. Verify server URL in SMS Device record matches the phone's config
4. Check webhook config in SMS Gateway server config.yml includes `system:ping`
5. Restart the Android app
6. Check Docker logs: `docker logs sms-gateway`

---

### SMS stuck in "Queued" status

**Symptoms:**
- SMS Queue entries remain "Queued" and never progress
- No SMS being sent

**Causes:**
1. SMS Gateway Settings → Enabled is off
2. No active/online devices
3. All devices at quota limit
4. All devices throttled
5. Scheduler not running

**Fixes:**
1. Check `SMS Gateway Settings.enabled` is 1
2. Check at least one device is Active and Online
3. Check `sent_today < daily_quota` on devices
4. Wait 60 seconds for throttle window to reset
5. Check Frappe scheduler is running: `bench doctor`
6. Manually trigger: `bench execute sms_relay.tasks.process_sms_queue`

---

### SMS marked as "Failed"

**Symptoms:**
- SMS Queue status changes to "Failed"
- Error message in SMS Log

**Common errors:**

| Error | Cause | Fix |
|---|---|---|
| `ConnectionError` | Cannot reach gateway server | Check server URL, network, Docker |
| `HTTPError 401` | Authentication failed | Check username/password in settings |
| `HTTPError 403` | Forbidden | Check credentials, check private token |
| `HTTPError 404` | Wrong API path | Check `api_path` setting (default: `/api/3rdparty/v1/message`) |
| `Timeout` | Server too slow | Increase `timeout` setting |
| `No gateway URL configured` | Device has no URL, no global URL | Set URL in device or global settings |
| `No device available` | All devices offline/quota/throttled | Check device status, increase quota |

**Fix:** Click "Retry Now" on the SMS Queue entry, or wait for daily `retry_failed_sms` job.

---

### Delivery receipts not updating status

**Symptoms:**
- SMS sent but status stays "Sent" (never "Delivered")
- No webhook activity

**Causes:**
1. Webhook not configured on SMS Gateway server
2. Webhook URL incorrect
3. Webhook HMAC secret mismatch
4. Firewall blocking incoming requests

**Fixes:**
1. Check `config.yml` in SMS Gateway server has webhook URL configured
2. URL should be: `http://YOUR-FRAPPE-SITE/api/method/sms_relay.webhook_receiver.incoming_webhook`
3. Test webhook manually:
```bash
curl -X POST http://YOUR-FRAPPE-SITE/api/method/sms_relay.webhook_receiver.incoming_webhook \
  -H "Content-Type: application/json" \
  -d '{"event": "system:ping", "device_name": "My Phone"}'
```
4. Check SMS Gateway Settings → Webhook Enabled is checked
5. If HMAC configured, ensure secret matches between Frappe and server config

---

### Overdue reminders not sending

**Symptoms:**
- No overdue reminder SMS being generated
- Invoices are overdue but no SMS

**Causes:**
1. `send_overdue_reminders` is off
2. `reminder_intervals` doesn't match the days overdue
3. Customer has no phone number
4. Customer opted out

**Fixes:**
1. Check `SMS Gateway Settings.send_overdue_reminders` is 1
2. Check `reminder_intervals` — if set to "7,14,30,60,90" and invoice is 10 days overdue, no SMS sent (10 not in list)
3. Verify customer has a Contact with mobile_no or phone
4. Check `SMS Opt Out` table for the customer's phone

---

### Templates not rendering

**Symptoms:**
- SMS sends with raw template text instead of rendered values
- Or template renders to empty

**Causes:**
1. Jinja2 syntax error in template
2. Variable name doesn't exist in context
3. Template body is empty

**Fixes:**
1. Use SMS Template → "Preview" button to test rendering
2. Check variable names match the documented list for your event type
3. Use `{{ doc.fieldname }}` for document fields, `{{ variable_name }}` for context variables
4. Test with a simple template: `Hello {{ customer_name }}`

---

### Rate limiting too aggressive

**Symptoms:**
- SMS being skipped with throttle
- Queue building up

**Fix:**
1. Increase `rate_limit_per_minute` in SMS Gateway Settings (max: 60)
2. Add more devices to distribute load
3. Increase `batch_size` to process more per cycle

---

## Log Locations

| Log | Location | What it contains |
|---|---|---|
| SMS Log | SMS Relay → SMS Log | Complete SMS history with delivery status |
| SMS Queue | SMS Relay → SMS Queue | Pending/failed messages |
| Error Log | Setup → Error Log | Frappe error logs (search "SMS Relay") |
| Frappe Scheduler | `bench doctor` | Scheduler health |

## Performance Tips

1. **Keep batch_size reasonable** — 10 per minute is safe. Higher values may overwhelm devices.
2. **Monitor quota** — If daily_quota is too low, SMS will queue up. Increase or add devices.
3. **Clean logs** — Default 90-day retention keeps the Log table manageable. Adjust `log_retention_days` if needed.
4. **Multiple devices** — Add devices with different priorities for failover and load distribution.
