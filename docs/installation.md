# Installation Guide

## Prerequisites

- Frappe Framework v15+ with bench CLI
- ERPNext v15+ installed and configured
- MariaDB / MySQL running
- Python 3.10+
- Node.js 16+
- An Android phone with SMS Gateway app installed
- SMS Gateway server running (Docker or native)

## Step 1: Install the Android SMS Gateway

### Server Setup (Docker)

```bash
# Clone the SMS Gateway server
git clone https://github.com/AuroraLS/android-sms-gateway.git
cd android-sms-gateway

# Create config directory
mkdir -p config

# Create config.yml
cat > config.yml << 'EOF'
server:
  port: 8080
  auth:
    privateToken: "your-private-token-here"
  webhooks:
    - url: "http://your-frappe-site:8080/api/method/sms_relay.api.webhook_receiver.incoming_webhook"
      events:
        - sms:delivered
        - sms:failed
        - sms:received
        - system:ping
EOF

# Start the server
docker run -d \
  --name sms-gateway \
  -p 8080:8080 \
  -v $(pwd)/config:/app/config \
  ghcr.io/android-sms-gateway/server:latest
```

### Android Phone Setup

1. Install SMS Gateway app from GitHub Releases
2. Open app → Settings → Server URL → enter `http://YOUR-SERVER-IP:8080`
3. Enter credentials (private token)
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

1. Go to **SMS Relay → SMS Gateway Settings**
2. Fill in:
   - Enabled: ✓
   - Sender Name: Your sender label
   - Routing Strategy: Round Robin (recommended)
   - Enable Failover: ✓
   - Global Rate Limit: 60
3. Save

## Step 4: Add SMS Devices

1. Go to **SMS Relay → SMS Device → New**
2. Fill in:
   - Device Name: "Office Phone"
   - Gateway URL: `http://YOUR-SERVER-IP:8080`
   - Gateway Type: Android SMS Gateway
   - API Key: (from the Android app settings)
   - SIM Slot: 1
   - Priority: 0 (highest)
   - Hourly Quota: 500
   - Daily Quota: 5000
   - Active: ✓
3. Save

## Step 5: Create SMS Templates (Optional)

1. Go to **SMS Relay → SMS Template → New**
2. Enter template name and Jinja2 body:

```
Dear {{ doc.customer }}, your invoice {{ doc.name }} for {{ frappe.utils.fmt_money(doc.grand_total) }} is due on {{ doc.due_date }}. Please pay at your earliest convenience.
```

3. Check the character counter — GSM-7 allows 160 chars per SMS
4. Save

## Step 6: Set Up Notifications (Optional)

1. Go to **SMS Relay → SMS Notification → New**
2. Configure:
   - Reference DocType: Sales Invoice
   - Event: On Submit
   - Phone Field: customer_contact_person (or the field with phone)
   - Message Template: (your Jinja template)
   - Condition: `return doc.outstanding_amount > 0`
3. Save

## Step 7: Test

### Test Connection

```javascript
frappe.call({
    method: "sms_relay.api.endpoints.get_device_health",
    callback: function(r) {
        console.log(r.message);
    }
});
```

### Test Manual SMS

```javascript
frappe.call({
    method: "sms_relay.api.endpoints.send_sms_now",
    args: {
        recipient: "+1234567890",
        message: "Test SMS from SMS Relay!"
    }
});
```

### Test Document Flow

1. Create a Sales Invoice → Submit
2. Check SMS Queue for queued entry
3. Wait 1 minute → check SMS Log for sent status

## Post-Installation Checklist

- [ ] SMS Gateway server running and accessible
- [ ] Android phone connected and showing "Online"
- [ ] SMS Gateway Settings configured and enabled
- [ ] At least one SMS Device added and active
- [ ] Test SMS sent and received
- [ ] Webhook configured for delivery receipts
- [ ] (Optional) SMS Templates created
- [ ] (Optional) SMS Notifications configured
- [ ] (Optional) SMS Opt Out list populated
