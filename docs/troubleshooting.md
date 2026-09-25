# Troubleshooting Guide

## Quick Diagnostics

### Check if SMS relay is enabled
```python
frappe.get_single("SMS Gateway Settings").enabled
# Should return 1
```

### Check device status
```python
frappe.get_all("SMS Device", fields=["name", "device_name", "is_active", "is_online", "battery_level", "signal_strength", "sent_today", "daily_quota"])
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
frappe.get_all("SMS Log", order_by="creation desc", limit=10, fields=["name", "phone", "status", "delivery_status", "error_message"])
```

### Check webhook delivery queue
```python
frappe.get_all("SMS Webhook Delivery", filters={"status": ["!=", "Sent"]}, limit=10, fields=["name", "url", "status", "attempts", "next_retry_at"])
```

### Check scheduled messages
```python
frappe.get_all("SMS Queue", filters={"status": "Queued", "scheduled_at": ["is", "set"]}, limit=10, fields=["name", "recipient", "scheduled_at", "ttl_seconds"])
```

### Check message history
```python
frappe.get_all("SMS Log", order_by="creation desc", limit=10, fields=["name", "phone", "status", "message_id", "device_id"])
```

### Check opt-out list
```python
frappe.get_all("SMS Opt Out", filters={"opted_out": 1}, limit=10)
```

### Check notifications
```python
frappe.get_all("SMS Notification", filters={"disabled": 0}, fields=["name", "reference_doctype", "doctype_event"])
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
3. Server URL incorrect on the device
4. Health check not reaching Frappe

**Fixes:**
1. Open SMS Gateway app on phone → verify "Connected" status
2. Check phone can reach the server (same LAN or correct port forwarding)
3. Verify Server URL in SMS Device record matches the gateway server
4. Click **Check Device** to refresh device info
5. Restart the Android app
6. Check Docker logs: `docker logs sms-gateway`

---

### SMS stuck in "Queued" status

**Causes:**
1. SMS Gateway Settings → Enabled is off
2. No active/online devices (`is_active = 1`)
3. All devices at quota limit
4. Scheduler not running
5. Missing device credentials (username/password)

**Fixes:**
1. Check `SMS Gateway Settings.enabled` is 1
2. Check at least one device has `is_active = 1`
3. Check `sent_today < daily_quota` on devices
4. Check scheduler: `bench doctor`
5. Manually trigger: `bench execute sms_relay.tasks.process_sms_queue`
6. Verify device has username/password set (Basic Auth required)

---

### SMS marked as "Failed"

**Common errors:**

| Error | Cause | Fix |
|---|---|---|
| `ConnectionError` | Cannot reach gateway | Check server URL, network, Docker |
| `HTTP 401` | Auth failed | Check username/password on SMS Device |
| `HTTP 403` | Forbidden | Check credentials |
| `HTTP 404` | Wrong API path | Check API Path in SMS Gateway Settings |
| `Timeout` | Server too slow | Check network, increase Timeout setting |
| `No device available` | All devices offline/quota | Check device status |
| `No credentials: set username/password` | Missing Basic Auth | Set username/password on SMS Device |

**Fix:** Click "Retry" on SMS Queue, or wait for daily retry job.

---

### Delivery receipts not updating status

**Fixes:**
1. Confirm webhooks were registered — run **Check Device** (or `register_device_webhooks`) and verify `GET /api/3rdparty/v1/webhooks` lists every event with your webhook URL
2. The registered URL must be `https://.../api/method/sms_relay.api.webhook_receiver.incoming_webhook` (the gateway server rejects `http://` with `400 url must start with https://`; there is no `allow_http` option). Set it on **SMS Device → Webhook Callback URL** or **SMS Gateway Settings → Webhook URL**
3. Test webhook manually:
```bash
curl -X POST https://YOUR-FRAPPE-SITE/api/method/sms_relay.api.webhook_receiver.incoming_webhook \
  -H "Content-Type: application/json" \
  -d '{"event": "system:ping", "deviceId": "test"}'
```
4. Check Webhook HMAC Secret matches the app's Webhooks signing key
5. The **app** POSTs the webhooks itself, so the phone must be able to reach the https URL and trust its certificate (private CA: install it as a **user CA on the phone**). The phone also refreshes its webhook list every 24 h / when the Cloud Server connection starts / on an FCM push — toggle that connection in the app so newly registered hooks are fetched.
6. Check firewall allows incoming connections to Frappe on 443

---

### Notifications not triggering

**Causes:**
1. SMS Notification is disabled
2. Wrong event type (On Submit vs On Save)
3. Phone field doesn't contain phone number
4. Condition returning False
5. Jinja template error
6. Reference DocType mismatch

**Fixes:**
1. Check SMS Notification `disabled` is unchecked
2. Verify `doctype_event` matches your workflow (submit vs save)
3. Verify `field_name` matches a field on the DocType
4. Test condition: clear the Condition field (or use `1`) to always send
5. Use "Preview Message" button in the form
6. Check the linked SMS Template has a message_template body

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
2. Use "Preview Message" button to test rendering
3. Use `{{ doc.fieldname }}` for document fields
4. Test with simple template: `Hello {{ doc.customer }}`
5. Check Jinja2 syntax (no Python code in templates)
6. For Parameter mode: ensure Fields table has rows mapping `{{1}}`, `{{2}}` etc.

---

### Rate limiting too aggressive

**Fix:**
1. Increase `global_rate_limit` in SMS Gateway Settings
2. Add more devices to distribute load
3. Increase hourly/daily quotas on devices
4. Adjust `send_interval_min`/`send_interval_max` for gradual sending

---

### Messages expiring (TTL)

**Causes:**
1. `ttl_seconds` set too low
2. `valid_until` time already passed
3. Queue processing delayed (scheduler not running)

**Fix:**
1. Increase `ttl_seconds` or remove it
2. Set `valid_until` further in the future
3. Check scheduler: `bench doctor`
4. Manually trigger: `bench execute sms_relay.tasks.process_sms_queue`

---

### Messages stuck in "Cancelled" status

**Causes:**
1. Cancelled via `cancel_message` API
2. Cancelled by webhook `sms:cancelled` event
3. Opted-out recipient

**Fix:** This is expected behavior. Cancelled messages cannot be unsent. Re-queue with `retry_sms` if needed.

---

### Webhook deliveries failing repeatedly

**Causes:**
1. Registered webhook URL is `http://` — the gateway server hard-rejects it (`400 url must start with https://`; no `allow_http` option)
2. The phone has not fetched the new registrations yet (it syncs every 24 h / on Cloud Server connect / on FCM push)
3. The phone cannot reach the URL, or does not trust its certificate
4. Wrong URL (auto-detected instead of your LAN https endpoint)
5. HMAC secret mismatch

**Fix:**
1. Check `SMS Webhook Delivery` list for failed entries
2. Set the webhook URL to `https://YOUR-FRAPPE-SITE/api/method/sms_relay.api.webhook_receiver.incoming_webhook` on **SMS Device → Webhook Callback URL** (or **SMS Gateway Settings → Webhook URL**), then re-run **Check Device**
3. Toggle the Cloud Server connection in the app so it pulls the new webhook list (offline there is no FCM push to trigger it)
4. Test: `curl -X POST https://YOUR-FRAPPE-SITE/api/method/sms_relay.api.webhook_receiver.incoming_webhook -H "Content-Type: application/json" -d '{"event": "system:ping"}'`
5. Private CA: install it as a **user CA on the phone** — the app trusts user-installed CAs (see the wiki [Webhook Delivery](https://github.com/Manaa-Soft/sms_relay/wiki/Webhook-Delivery))
6. Check firewall allows incoming connections to Frappe on 443

---

## Log Locations

| Log | Location | What it contains |
|---|---|---|
| SMS Log | SMS Relay → SMS Log | Complete SMS history with delivery status |
| SMS Queue | SMS Relay → SMS Queue | Pending/failed/scheduled messages |
| SMS Outbox | SMS Relay → SMS Outbox | Retry queue with backoff |
| SMS Webhook Delivery | SMS Relay → SMS Webhook Delivery | Failed webhook retry queue |
| SMS Bulk Message | SMS Relay → SMS Bulk Message | Campaign status and counts |
| SMS Notification Log | SMS Relay → SMS Notification Log | Notification delivery audit |
| Error Log | Setup → Error Log | Frappe error logs (search "SMS Relay") |

## Performance Tips

1. **Monitor quotas** — If daily_quota is too low, SMS queues up
2. **Multiple devices** — Add devices for failover and load distribution
3. **Priority tiers** — Use High for OTP/payment, Low for marketing
4. **Clean logs** — Default 90-day retention keeps tables manageable
5. **Use condition filters** — Don't send SMS for every document, use conditions
6. **Check credentials** — Ensure all SMS Devices have username/password set for Basic Auth
