import frappe
from unittest.mock import patch, MagicMock
from sms_relay.tests.conftest import SMSRelayTestCase
from sms_relay.core.sms_engine import (
    _select_device,
    _select_device_round_robin,
    _select_device_priority,
    _check_quota,
    _throttle_check,
    _log_sms,
    _enqueue_sms,
    _render_template,
    cancel_message,
    _send_android_gateway,
)


class TestDeviceSelection(SMSRelayTestCase):
    """Test device routing strategies."""

    def _create_second_device(self):
        if not frappe.db.exists("SMS Device", "Test Phone 2"):
            device = frappe.new_doc("SMS Device")
            device.device_name = "Test Phone 2"
            device.server_url = "http://localhost:8085"
            device.username = "test_user_2"
            device.password = "test_pass_2"
            device.sim_number = 2
            device.priority = 5
            device.is_active = 1
            device.daily_quota = 200
            device.hourly_quota = 500
            device.gateway_type = "Android SMS Gateway"
            device.insert(ignore_permissions=True)

    def test_select_device_returns_active(self):
        device = _select_device("+15551234567")
        self.assertIn(device, ["Test Phone"])

    def test_select_device_returns_none_when_no_active(self):
        frappe.db.set_value("SMS Device", "Test Phone", "is_active", 0)
        frappe.db.commit()
        device = _select_device("+15551234567")
        self.assertIsNone(device)

    def test_round_robin_cycles(self):
        self._create_second_device()
        frappe.db.set_value("SMS Device", "Test Phone", "is_active", 1)
        frappe.db.set_value("SMS Device", "Test Phone 2", "is_active", 1)
        frappe.db.commit()
        frappe.cache().delete_value("sms_round_robin_counter")

        devices = frappe.get_all("SMS Device", filters={"is_active": 1}, fields=["name", "device_name", "priority", "hourly_quota", "daily_quota"])
        result1 = _select_device_round_robin(devices, "+15551111111")
        result2 = _select_device_round_robin(devices, "+15552222222")
        self.assertNotEqual(result1, result2) if len(devices) >= 2 else None

    def test_priority_strategy_picks_highest_priority(self):
        self._create_second_device()
        frappe.db.set_value("SMS Device", "Test Phone", "is_active", 1)
        frappe.db.set_value("SMS Device", "Test Phone 2", "is_active", 1)
        frappe.db.set_value("SMS Device", "Test Phone", "priority", 10)
        frappe.db.set_value("SMS Device", "Test Phone 2", "priority", 0)
        frappe.db.commit()

        settings = frappe.get_single("SMS Gateway Settings")
        settings.routing_strategy = "Priority"
        settings.save(ignore_permissions=True)
        frappe.cache().delete_value("sms_relay_settings")

        devices = frappe.get_all("SMS Device", filters={"is_active": 1}, fields=["name", "device_name", "priority", "hourly_quota", "daily_quota"], order_by="priority asc")
        result = _select_device_priority(devices, "+15551234567")
        self.assertEqual(result, "Test Phone 2")


class TestQuotaAndThrottle(SMSRelayTestCase):
    """Test quota checking and rate limiting."""

    def test_check_quota_within_limit(self):
        device = frappe.get_all("SMS Device", filters={"device_name": "Test Phone"}, fields=["name", "hourly_quota", "daily_quota"])[0]
        self.assertTrue(_check_quota(device))

    def test_throttle_within_limit(self):
        self.assertTrue(_throttle_check("Test Phone"))


class TestLogAndEnqueue(SMSRelayTestCase):
    """Test SMS logging and queueing."""

    def test_log_sms_creates_entry(self):
        log = _log_sms("+15551234567", "Test message", "Sent", device_name="Test Phone")
        self.assertEqual(log.phone, "+15551234567")
        self.assertEqual(log.status, "Sent")
        self.assertEqual(log.device, "Test Phone")
        self.assertTrue(log.name)

    def test_log_sms_with_message_id(self):
        log = _log_sms("+15551234567", "Test", "Sent", message_id="msg-123", device_id="dev-001")
        self.assertEqual(log.message_id, "msg-123")
        self.assertEqual(log.device_id, "dev-001")

    def test_log_sms_with_error(self):
        log = _log_sms("+15551234567", "Test", "Failed", error="Connection refused")
        self.assertEqual(log.error_message, "Connection refused")

    def test_enqueue_sms_creates_queue_entry(self):
        queue = _enqueue_sms("+15551234567", "Test message", "Test Phone", priority="High")
        self.assertEqual(queue.recipient, "+15551234567")
        self.assertEqual(queue.message, "Test message")
        self.assertEqual(queue.status, "Queued")
        self.assertEqual(queue.priority_tier, "High")
        self.assertEqual(queue.device, "Test Phone")

    def test_enqueue_sms_with_ttl(self):
        queue = _enqueue_sms("+15551234567", "Test", ttl_seconds=3600)
        self.assertEqual(queue.ttl_seconds, 3600)

    def test_enqueue_sms_with_message_id(self):
        queue = _enqueue_sms("+15551234567", "Test", message_id="unique-123")
        self.assertEqual(queue.message_id, "unique-123")

    def test_enqueue_sms_with_valid_until(self):
        from frappe.utils import add_to_date
        valid = add_to_date(frappe.utils.now_datetime(), days=1)
        queue = _enqueue_sms("+15551234567", "Test", valid_until=valid)
        self.assertIsNotNone(queue.valid_until)


class TestCancelMessage(SMSRelayTestCase):
    """Test message cancellation."""

    def test_cancel_queued_message(self):
        queue = _enqueue_sms("+15551234567", "To be cancelled", "Test Phone")
        frappe.db.commit()
        result = cancel_message(queue.name)
        self.assertEqual(result["status"], "cancelled")

        queue.reload()
        self.assertEqual(queue.status, "Cancelled")
        self.assertIsNotNone(queue.cancelled_at)

    def test_cancel_non_queued_throws(self):
        queue = _enqueue_sms("+15551234567", "Sent message", "Test Phone")
        frappe.db.commit()
        frappe.db.set_value("SMS Queue", queue.name, "status", "Sent")
        frappe.db.commit()
        with self.assertRaises(frappe.ValidationError):
            cancel_message(queue.name)


class TestRenderTemplate(SMSRelayTestCase):
    """Test Jinja template rendering."""

    def test_basic_render(self):
        result = _render_template("Test Template", {"doc": {"customer": "John", "grand_total": 1000}})
        self.assertIn("John", result)
        self.assertIn("1000", result)

    def test_render_with_whitespace_body(self):
        tmpl = frappe.new_doc("SMS Template")
        tmpl.template_name = "Space Template"
        tmpl.category = "UTILITY"
        tmpl.language = "en"
        tmpl.message_template = "{{ ' ' * 10 }}"
        tmpl.insert(ignore_permissions=True)
        result = _render_template("Space Template", {})
        self.assertEqual(result.strip(), "")


class TestSendAndroidGateway(SMSRelayTestCase):
    """Test Android gateway dispatch with mocking."""

    def _get_device(self):
        return frappe.get_doc("SMS Device", "Test Phone")

    @patch("sms_relay.gateway.client.requests.post")
    def test_successful_send(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"id": "msg-001", "requestId": "req-001"}
        mock_post.return_value = mock_resp

        result = _send_android_gateway(self._get_device(), "+15551234567", "Test message", "")
        self.assertTrue(result["success"])
        self.assertEqual(result["message_id"], "msg-001")

    @patch("sms_relay.gateway.client.requests.post")
    def test_auth_failure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_resp.headers = {"content-type": "text/plain"}
        mock_post.return_value = mock_resp

        result = _send_android_gateway(self._get_device(), "+15551234567", "Test message", "")
        self.assertFalse(result["success"])
        self.assertIn("401", result["error"])

    @patch("sms_relay.gateway.client.requests.post")
    def test_connection_error(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        result = _send_android_gateway(self._get_device(), "+15551234567", "Test message", "")
        self.assertFalse(result["success"])
        self.assertIn("Connection error", result["error"])

    def test_no_server_url(self):
        frappe.db.set_value("SMS Device", "Test Phone", "server_url", "")
        frappe.db.commit()
        result = _send_android_gateway(self._get_device(), "+15551234567", "Test message", "")
        self.assertFalse(result["success"])
        self.assertIn("No server URL", result["error"])

    def test_no_username(self):
        frappe.db.set_value("SMS Device", "Test Phone", {
            "server_url": "http://localhost:8085",
            "username": "",
        })
        frappe.db.commit()
        result = _send_android_gateway(self._get_device(), "+15551234567", "Test message", "")
        self.assertFalse(result["success"])
        self.assertIn("No credentials", result["error"])

    @patch("sms_relay.gateway.client.requests.post")
    def test_idempotency_skips_duplicate(self, mock_post):
        _log_sms("+15551234567", "Test", "Sent", message_id="idem-123")
        queue = _enqueue_sms("+15551234567", "Test", message_id="idem-123")
        frappe.db.commit()

        result = _send_android_gateway(self._get_device(), "+15551234567", "Test message", "", queue_doc=queue)
        self.assertTrue(result["success"])
        self.assertEqual(result["message_id"], "idem-123")
        mock_post.assert_not_called()

    @patch("sms_relay.gateway.client.requests.post")
    def test_payload_includes_id_schedule_and_valid_until(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"id": "m-1"}
        mock_post.return_value = mock_resp

        from frappe.utils import add_to_date, now_datetime
        schedule = add_to_date(now_datetime(), minutes=30)
        result = _send_android_gateway(
            self._get_device(), "+15551234567", "Hello", "",
            message_id="m-1", ttl_seconds=120, schedule_at=schedule,
        )
        self.assertTrue(result["success"])
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["id"], "m-1")
        self.assertEqual(payload["textMessage"], {"text": "Hello"})
        self.assertEqual(payload["phoneNumbers"], ["+15551234567"])
        self.assertIn("scheduleAt", payload)
        self.assertIn("validUntil", payload)

    @patch("sms_relay.gateway.client.requests.post")
    def test_payload_sends_data_message(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"id": "m-2"}
        mock_post.return_value = mock_resp

        result = _send_android_gateway(
            self._get_device(), "+15551234567", "Hello", "",
            message_id="m-2", data_payload="aGVsbG8=", data_port=9200,
        )
        self.assertTrue(result["success"])
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["dataMessage"], {"data": "aGVsbG8=", "port": 9200})
        self.assertNotIn("textMessage", payload)

    @patch("sms_relay.gateway.client.requests.post")
    def test_send_batch_recipients(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"id": "m-3"}
        mock_post.return_value = mock_resp

        result = _send_android_gateway(
            self._get_device(), ["+15551234567", "+15557654321"], "Hello", "", message_id="m-3",
        )
        self.assertTrue(result["success"])
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["phoneNumbers"], ["+15551234567", "+15557654321"])
