# Installation Guide

## Prerequisites

- Frappe Framework v15+ with bench CLI (tested on v16)
- ERPNext v15+ installed and configured
- MariaDB / MySQL running
- Python 3.10+ (tested on 3.14)
- Node.js 16+
- An Android phone with SMS Gateway app installed
- SMS Gateway server running in Docker

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
gateway:
  mode: private    # "public" or "private"
  private_token: "your-secret-token"  # Used for phone registration in private mode

server:
  port: 3000
  auth:
    jwt:
      secret: "your-jwt-secret"
  webhooks:
    - url: "http://YOUR-FRAPPE-SITE/api/method/sms_relay.api.webhook_receiver.incoming_webhook"
      events:
        - sms:delivered
        - sms:failed
        - sms:sent
        - sms:cancelled
        - sms:received
        - sms:data-received
        - mms:received
        - mms:downloaded
        - app:started
        - system:ping
EOF

# Start the server (port 8085 via nginx or direct)
docker run -d \
  --name sms-gateway \
  -p 8085:3000 \
  -v $(pwd)/config:/app/config \
  ghcr.io/android-sms-gateway/server:latest
```

**Note:** The Go server runs on port 3000 internally. Map it to 8085 (or any port) on the host. If using nginx, configure it to proxy 8085 → 3000.

### Understanding Authentication

The Docker server has two API namespaces:

| Endpoint | Purpose | Auth |
|---|---|---|
| `POST /api/3rdparty/v1/message` | Frappe sends SMS | **Basic Auth** with device `login:password` |
| `POST /api/mobile/v1/device` | Phone registers | **Bearer `private_token`** (private mode) or Basic Auth |

The `private_token` in `config.yml` secures **device registration** — it's a server-side secret, NOT sent by Frappe.

When a phone registers, the server returns:
```json
{
    "id": "device-id",
    "token": "bearer-token-for-phone",
    "login": "G9G_SA",
    "password": "123456789101112"
}
```

The `login`/`password` are what you enter on the **SMS Device** record in Frappe. Frappe uses these for Basic Auth when sending SMS.

### Android Phone Setup

1. Install SMS Gateway app from GitHub Releases
2. Open app → Settings → Server URL → enter `http://YOUR-SERVER-IP:8085`
3. In **private mode**: enter the `private_token` from `config.yml`
4. Phone registers and shows "Connected" status
5. Note the `login`/`password` shown in the app — you'll need these for Frappe

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
   - Server URL: `http://YOUR-SERVER-IP:8085`
   - API Path: `/api/3rdparty/v1/message` (default)
   - Routing Strategy: Round Robin (recommended)
   - Enable Failover: ✓
   - Global Rate Limit: 60
3. Save
4. Click **Test Connection** to verify

## Step 4: Add SMS Device

1. Go to **SMS Relay → SMS Device → New**
2. Fill in:
   - Device Name: "Office Phone"
   - Mode: Private
   - Server URL: `http://YOUR-SERVER-IP:8085`
   - Username: (the `login` from the phone app — e.g. `G9G_SA`)
   - Password: (the `password` from the phone app — e.g. `123456789101112`)
   - Priority: 0 (highest)
   - Active: ✓
3. Save
4. Click **Connect Device** to auto-fetch device info

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
   - Notification Type: DocType notification
   - Reference DocType: Sales Invoice
   - DocType Event: After Submit
   - Field Name: customer_contact_person (or the field with phone)
   - Template: Select your SMS Template
   - Template Type: Jinja (or Parameter if using positional params)
   - Condition: `return doc.outstanding_amount > 0`
3. Save

## Step 7: Test

### Test Connection

```javascript
frappe.call({
    method: "sms_relay.api.endpoints.test_connection",
    args: { device_name: "Office Phone" },  // optional
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

- [ ] SMS Gateway server running and accessible on port 8085
- [ ] Android phone connected and showing "Connected"
- [ ] SMS Gateway Settings configured and enabled
- [ ] Test Connection successful
- [ ] At least one SMS Device added and active with correct username/password
- [ ] Connect Device successful (device info auto-filled)
- [ ] Test SMS sent and received
- [ ] Webhook configured for delivery receipts (in server config.yml)
- [ ] (Optional) SMS Templates created
- [ ] (Optional) SMS Notifications configured
- [ ] (Optional) SMS Opt Out list populated
