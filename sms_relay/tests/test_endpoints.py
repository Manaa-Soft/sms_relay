import json
import frappe
from unittest.mock import patch, MagicMock
from sms_relay.tests.conftest import SMSRelayTestCase
from sms_relay.api.endpoints import (
    test_connection,
    connect_device,
    send_sms_now,
    cancel_message,
    get_message_history,
    get_inbox,
    get_device_health,
    get_structured_health,
    get_sms_stats,
    preview_template,
    retry_sms,
    get_notification_preview,
)


class TestSendSmsNow(SMSRelayTestCase):
    """Test the send_sms_now endpoint."""

    @patch("sms_relay.core.sms_engine._send_to_device")
    def test_send_single_recipient(self, mock_send):
        mock_send.return_value = {"success": True, "message_id": "gw-001"}
        result = send_sms_now(recipient="+15551234567", message="Test SMS")
        self.assertEqual(result["status"], "sent")
        self.assertIn("+15551234567", result["recipients"])

    @patch("sms_relay.core.sms_engine._send_to_device")
    def test_send_multiple_recipients(self, mock_send):
        mock_send.return_value = {"success": True, "message_id": "gw-001"}
        result = send_sms_now(recipient=["+15551111111", "+15552222222"], message="Bulk test")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(len(result["recipients"]), 2)

    def test_send_no_recipient_throws(self):
        with self.assertRaises(frappe.ValidationError):
            send_sms_now(message="Test")

    def test_send_no_message_throws(self):
        with self.assertRaises(frappe.ValidationError):
            send_sms_now(recipient="+15551234567")

    @patch("sms_relay.core.sms_engine._send_to_device")
    def test_idempotency_returns_already_sent(self, mock_send):
        mock_send.return_value = {"success": True, "message_id": "gw-001"}
        send_sms_now(recipient="+15551234567", message="First", message_id="idem-test-001")
        result = send_sms_now(recipient="+15551234567", message="Second", message_id="idem-test-001")
        self.assertEqual(result["status"], "already_sent")

    @patch("sms_relay.core.sms_engine._send_to_device")
    def test_send_with_ttl(self, mock_send):
        mock_send.return_value = {"success": True}
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "TTL test"
        queue.status = "Queued"
        queue.ttl_seconds = 3600
        queue.insert(ignore_permissions=True)
        frappe.db.commit()
        self.assertEqual(queue.ttl_seconds, 3600)


class TestCancelMessageEndpoint(SMSRelayTestCase):
    """Test the cancel_message endpoint."""

    def test_cancel_queued(self):
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Cancel me"
        queue.status = "Queued"
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        result = cancel_message(queue_name=queue.name)
        self.assertEqual(result["status"], "cancelled")

    def test_cancel_no_name_throws(self):
        with self.assertRaises(frappe.ValidationError):
            cancel_message()


class TestGetMessageHistory(SMSRelayTestCase):
    """Test message history endpoint."""

    def test_returns_logs(self):
        frappe.get_doc({
            "doctype": "SMS Log",
            "phone": "+15551234567",
            "message": "History test",
            "status": "Sent",
            "device": "Test Phone",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        result = get_message_history(limit=10)
        self.assertIn("messages", result)
        self.assertIn("total", result)
        self.assertGreater(result["total"], 0)

    def test_filter_by_status(self):
        result = get_message_history(status="Failed", limit=10)
        self.assertIn("messages", result)


class TestGetInbox(SMSRelayTestCase):
    """Test inbox endpoint."""

    def test_returns_received(self):
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Incoming test"
        queue.status = "Received"
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        result = get_inbox(limit=10)
        self.assertIn("messages", result)


class TestGetDeviceHealth(SMSRelayTestCase):
    """Test device health endpoint."""

    def test_returns_device_list(self):
        result = get_device_health()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        self.assertIn("name", result[0])
        self.assertIn("sent_today", result[0])


class TestGetStructuredHealth(SMSRelayTestCase):
    """Test structured health endpoint."""

    def test_returns_structure(self):
        result = get_structured_health()
        self.assertIn("status", result)
        self.assertIn("checks", result)
        self.assertIn("total_devices", result)
        self.assertIn("online_devices", result)
        self.assertIn(result["status"], ["pass", "warn", "fail"])


class TestGetSmsStats(SMSRelayTestCase):
    """Test SMS stats endpoint."""

    def test_returns_stats(self):
        result = get_sms_stats()
        self.assertIn("sent_today", result)
        self.assertIn("failed_today", result)
        self.assertIn("queued", result)
        self.assertIn("total_devices", result)


class TestPreviewTemplate(SMSRelayTestCase):
    """Test template preview endpoint."""

    def test_preview_with_text(self):
        result = preview_template(message_text="Hello World")
        self.assertEqual(result["message"], "Hello World")
        self.assertIn("sms_info", result)

    def test_preview_with_template(self):
        tmpl = frappe.new_doc("SMS Template")
        tmpl.template_name = "Simple Preview"
        tmpl.category = "UTILITY"
        tmpl.language = "en"
        tmpl.message_template = "Hello, this is a simple message."
        tmpl.insert(ignore_permissions=True)
        result = preview_template(template_name="Simple Preview")
        self.assertIn("message", result)


class TestRetrySms(SMSRelayTestCase):
    """Test retry endpoint."""

    def test_retry_failed(self):
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Retry me"
        queue.status = "Failed"
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        result = retry_sms(queue_name=queue.name)
        self.assertEqual(result["status"], "requeued")

    def test_retry_no_name_throws(self):
        with self.assertRaises(frappe.ValidationError):
            retry_sms()


class TestTestConnection(SMSRelayTestCase):
    """Test connection endpoint."""

    @patch("sms_relay.api.endpoints.requests.get")
    def test_successful_connection(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"id": "device-001", "name": "Test"}
        mock_get.return_value = mock_resp

        result = test_connection(device_name="Test Phone")
        self.assertTrue(result["success"])

    def test_no_url_returns_error(self):
        frappe.db.set_value("SMS Device", "Test Phone", "server_url", "")
        frappe.db.commit()
        result = test_connection(device_name="Test Phone")
        self.assertFalse(result["success"])

    @patch("sms_relay.api.endpoints.requests.get")
    def test_connection_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("timeout")
        result = test_connection(device_name="Test Phone")
        self.assertFalse(result["success"])


class TestConnectDevice(SMSRelayTestCase):
    """Test connect_device endpoint."""

    @patch("sms_relay.api.endpoints.requests.get")
    def test_successful_connect(self, mock_get):
        def side_effect(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if "health" in url:
                mock_resp.json.return_value = {"version": "1.67.0", "checks": {"battery:level": {"observedValue": 85}}}
            else:
                mock_resp.json.return_value = {"id": "dev-001", "name": "Galaxy", "simCards": [{"carrierName": "Vodafone", "phoneNumber": "+1234"}]}
            return mock_resp

        mock_get.side_effect = side_effect
        result = connect_device(device_name="Test Phone")
        self.assertTrue(result["success"])

    def test_no_device_name_throws(self):
        with self.assertRaises(frappe.ValidationError):
            connect_device()
