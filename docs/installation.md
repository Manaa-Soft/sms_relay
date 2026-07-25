# Installation Guide

## Prerequisites
- Frappe Framework v14+ / v15+ with bench CLI
- ERPNext v14+ installed and configured
- MariaDB / MySQL running
- Python 3.10+
- Node.js 16+
- An Android phone with SMS Gateway app installed
- SMS Gateway server running (Docker or native)

## Step 1: Install the Android SMS Gateway

### Server Setup (Docker)
```bash
# Clone the SMS Gateway server
git clone https://github.com/bipin2017/sms-gateway.git
cd sms-gateway

# Create config directory
mkdir -p config

# Create config.yml
cat > config.yml << 'EOF'
server:
  port: 3000
  auth:
    privateToken: "your-private-token-here"
  webhooks:
    - url: "http://your-frappe-site:8080/api/method/sms_relay.webhook_receiver.incoming_webhook"
      events:
        - sms:delivered
        - sms:failed
        - system:ping
EOF

# Start the server
docker run -d \
  --name sms-gateway \
  -p 3000:3000 \
  -v $(pwd)/config:/app/config \
  ghcr.io/android-sms-gateway/server:latest
```

### Android Phone Setup
1. Install SMS Gateway app from GitHub Releases (use `app-insecure.apk` for HTTP)
2. Open app → Settings → Server URL → enter `http://YOUR-SERVER-IP:3000`
3. Enter credentials (username/password or private token)
4. Select connection mode (Private for LAN, Cloud for internet)
5. Phone should show "Connected" status

## Step 2: Install sms_relay App

### Option A: From GitHub (recommended)
```bash
cd /path/to/frappe-bench
bench get-app https://github.com/Manaa-Soft/sms_relay.git
bench --site your-site install-app sms_relay
bench migrate
bench build --app sms_relay
bench restart
```

### Option B: From local directory
```bash
cd /path/to/frappe-bench
bench get-app /path/to/sms_relay
bench --site your-site install-app sms_relay
bench migrate
bench build --app sms_relay
bench restart
```

## Step 3: Configure SMS Gateway Settings

1. Go to ERPNext → Setup → SMS Gateway Settings
2. Fill in:
   - Enabled: ✓
   - Server URL: `http://YOUR-SERVER-IP:3000`
   - API Path: `/api/3rdparty/v1/message`
   - Username: your gateway username
   - Password: your gateway password
   - Send Invoice SMS: ✓
   - Send Payment SMS: ✓
   - Send Overdue Reminders: ✓
3. Save

## Step 4: Add SMS Devices

1. Go to SMS Relay → SMS Device → New
2. Fill in:
   - Device Name: "My Phone"
   - Device ID: (from the Android app)
   - Connection Mode: Private
   - SIM Number: 1
   - Priority: 0 (highest)
   - Active: ✓
   - Daily Quota: 200
3. Save and verify the device shows "Online"

## Step 5: Create SMS Templates (Optional)

1. Go to SMS Relay → SMS Template → New
2. Choose Event type
3. Write Jinja2 template:
```
Dear {{ customer_name }}, your invoice {{ name }} for {{ grand_total }} is due on {{ due_date }}. Outstanding: {{ outstanding_amount }}. Thank you!
```
4. Save

## Step 6: Test

### Test Connection
1. SMS Gateway Settings → click "Test Connection"
2. Should show "Connection successful"

### Test Manual SMS
1. SMS Template → select a template → click "Send Test SMS"
2. Enter phone number → Send
3. Check SMS Log for delivery status

### Test Document Flow
1. Create a Sales Invoice → Submit
2. Check SMS Queue for queued entry
3. Wait 1 minute → check SMS Log for sent status

## Troubleshooting

### Phone shows "Offline"
- Check server URL is correct
- Check phone and server are on same network
- Restart the Android app
- Check Docker logs: `docker logs sms-gateway`

### SMS not sending
- Check SMS Gateway Settings → Enabled is checked
- Check at least one SMS Device is Active and Online
- Check daily quota not exceeded
- Check rate limit not exceeded
- Check SMS Log for error messages

### Webhook not receiving delivery receipts
- Check webhook URL in SMS Gateway server config.yml
- Check firewall allows incoming connections to webhook URL
- Check SMS Gateway Settings → Webhook Enabled is checked

### Templates not rendering
- Check template syntax (Jinja2)
- Check variable names match the documented list
- Use SMS Template → Preview button to test
