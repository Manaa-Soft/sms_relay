# Troubleshooting Guide

## Quick Diagnostics

### Check if SMS relay is enabled
```python
frappe.get_single("SMS Gateway Settings").enabled
# Should return 1
```

### Check device status
```python
frappe.get_all("SMS Device", fields=["name", "device_name", "is_active", "battery_level", "signal_strength", "sent_today", "daily_quota"])
```

### Check queue status
```python
frappe.get_all("SMS Queue", filters={"status": "Queued"}, limit=10)
```

### Check outbox status
```python
frappe.get_all("SMS Outbox", filters={"status": ["!=", "Sent"]}, limit=10)
```

### Check recent SMS logs
```python
frappe.get_all("SMS Log", order_by="creation desc", limit=10, fields=["name", "phone_number", "status", "delivery_status", "error"])
```

### Check opt-out list
```python
frappe.get_all("SMS Opt Out", filters={"opted_out": 1}, limit=10)
```

### Check notifications
```python
frappe.get_all("SMS Notification", filters={"enabled": 1}, fields=["name", "reference_doctype", "event"])
```

### Check bulk campaigns
```python
frappe.get_all("SMS Bulk Message", filters={"status": ["in", ["Processing", "Draft"]]}, limit=10)
```

---

## Common Issues

### Phone shows "Offline" in SMS Device

**Causes:**
1. Phone app not connected to server
2. Network connectivity issue
3. Gateway URL incorrect
4. Health check not reaching Frappe

**Fixes:**
1. Open SMS Gateway app on phone → verify "Connected" status
2. Check phone can reach the server
3. Verify Gateway URL in SMS Device record
4. Check webhook config includes `system:ping`
5. Restart the Android app
6. Check Docker logs: `docker logs sms-gateway`

---

### SMS stuck in "Queued" status

**Causes:**
1. SMS Gateway Settings → Enabled is off
2. No active/online devices
3. All devices at quota limit
4. All devices throttled
5. Scheduler not running

**Fixes:**
1. Check `SMS Gateway Settings.enabled` is 1
2. Check at least one device is Active
3. Check `sent_today < daily_quota` on devices
4. Wait 60 seconds for throttle window to reset
5. Check scheduler: `bench doctor`
6. Manually trigger: `bench execute sms_relay.tasks.process_sms_queue`

---

### SMS marked as "Failed"

**Common errors:**

| Error | Cause | Fix |
|---|---|---|
| `ConnectionError` | Cannot reach gateway | Check gateway URL, network, Docker |
| `HTTPError 401` | Auth failed | Check API key |
| `HTTPError 403` | Forbidden | Check credentials |
| `HTTPError 404` | Wrong API path | Check API path |
| `Timeout` | Server too slow | Check network, increase timeout |
| `No device available` | All devices offline/quota | Check device status |

**Fix:** Click "Retry" on SMS Queue, or wait for daily retry job.

---

### Delivery receipts not updating status

**Fixes:**
1. Check `config.yml` has webhook URL configured
2. URL: `http://YOUR-FRAPPE-SITE/api/method/sms_relay.api.webhook_receiver.incoming_webhook`
3. Test webhook manually:
```bash
curl -X POST http://YOUR-FRAPPE-SITE/api/method/sms_relay.api.webhook_receiver.incoming_webhook \
  -H "Content-Type: application/json" \
  -d '{"event": "system:ping", "deviceId": "test"}'
```
4. Check Webhook Secret matches between Frappe and server config
5. Check firewall allows incoming connections

---

### Notifications not triggering

**Causes:**
1. SMS Notification not enabled
2. Wrong event type (On Submit vs On Save)
3. Phone field doesn't contain phone number
4. Condition returning False
5. Jinja template error

**Fixes:**
1. Check SMS Notification is enabled
2. Verify event matches your workflow (submit vs save)
3. Verify phone_field name matches a field on the DocType
4. Test condition: `return True` to always send
5. Use "Test Notification" button in the form

---

### Bulk messages not processing

**Causes:**
1. Bulk Message status not "Draft" or "Processing"
2. All recipients already processed
3. Scheduler not running

**Fixes:**
1. Check status is "Draft" or "Processing"
2. Check recipients table has "Pending" entries
3. Check scheduler: `bench doctor`
4. Manually trigger: `bench execute sms_relay.tasks.process_bulk_messages`

---

### Templates not rendering

**Fixes:**
1. Use SMS Template → check character counter
2. Use "Preview" button to test rendering
3. Use `{{ doc.fieldname }}` for document fields
4. Test with simple template: `Hello {{ doc.customer }}`
5. Check Jinja2 syntax (no Python code in templates)

---

### Rate limiting too aggressive

**Fix:**
1. Increase `global_rate_limit` in SMS Gateway Settings
2. Add more devices to distribute load
3. Increase hourly/daily quotas on devices

---

## Log Locations

| Log | Location | What it contains |
|---|---|---|
| SMS Log | SMS Relay → SMS Log | Complete SMS history with delivery status |
| SMS Queue | SMS Relay → SMS Queue | Pending/failed messages |
| SMS Outbox | SMS Relay → SMS Outbox | Retry queue with backoff |
| SMS Bulk Message | SMS Relay → SMS Bulk Message | Campaign status and counts |
| SMS Notification Log | SMS Relay → SMS Notification Log | Notification delivery audit |
| Error Log | Setup → Error Log | Frappe error logs (search "SMS Relay") |

## Performance Tips

1. **Keep batch_size reasonable** — 10 per minute is safe for most gateways
2. **Monitor quotas** — If daily_quota is too low, SMS queues up
3. **Multiple devices** — Add devices for failover and load distribution
4. **Priority tiers** — Use High for OTP/payment, Low for marketing
5. **Clean logs** — Default 90-day retention keeps tables manageable
6. **Use condition filters** — Don't send SMS for every document, use conditions
