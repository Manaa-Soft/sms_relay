import json
import frappe
from unittest.mock import patch, MagicMock
from sms_relay.tests.conftest import SMSRelayTestCase
from sms_relay.api.webhook_receiver import (
    incoming_webhook,
    _handle_delivery_report,
    _handle_cancelled_report,
    _handle_incoming_sms,
    _handle_app_started,
    _is_duplicate_webhook,
    _mark_webhook_seen,
    _enqueue_webhook_delivery,
)


class TestIdempotency(SMSRelayTestCase):
    """Test webhook idempotency markers."""

    def test_first_call_returns_false(self):
        frappe.cache().delete_value("webhook_test_prefix_abc")
        result = _is_duplicate_webhook({"test": "abc"}, "test_prefix")
        self.assertFalse(result)

    def test_second_call_returns_true(self):
        frappe.cache().delete_value("webhook_test_prefix_def")
        _mark_webhook_seen({"test": "def"}, "test_prefix")
        result = _is_duplicate_webhook({"test": "def"}, "test_prefix")
        self.assertTrue(result)

    def test_delivery_event_types_do_not_collide(self):
        payload = {"id": "gw-1"}
        self.assertFalse(_is_duplicate_webhook(payload, "delivery_report_sms:sent"))
        _mark_webhook_seen(payload, "delivery_report_sms:sent")
        self.assertTrue(_is_duplicate_webhook(payload, "delivery_report_sms:sent"))
        self.assertFalse(_is_duplicate_webhook(payload, "delivery_report_sms:delivered"))


class TestDeliveryReport(SMSRelayTestCase):
    """Test delivery report handling."""

    def test_delivered_status(self):
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Test"
        queue.status = "Sent"
        queue.gateway_message_id = "gw-001"
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        _handle_delivery_report({"id": "gw-001", "phoneNumber": "+15551234567"}, "sms:delivered")
        queue.reload()
        self.assertEqual(queue.status, "Sent")

    def test_cancelled_status(self):
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Test"
        queue.status = "Sent"
        queue.gateway_message_id = "gw-cancel-001"
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        _handle_cancelled_report({"id": "gw-cancel-001"})
        queue.reload()
        self.assertEqual(queue.status, "Cancelled")


class TestIncomingSms(SMSRelayTestCase):
    """Test incoming SMS handling."""

    def test_creates_queue_entry(self):
        count_before = frappe.db.count("SMS Queue", {"status": "Received"})
        _handle_incoming_sms({
            "phone": "+15551234567",
            "message": "STOP",
            "profileName": "Test User",
        })
        count_after = frappe.db.count("SMS Queue", {"status": "Received"})
        self.assertGreater(count_after, count_before)

    def test_empty_phone_ignored(self):
        count_before = frappe.db.count("SMS Queue", {"status": "Received"})
        _handle_incoming_sms({"phone": "", "message": "Test"})
        count_after = frappe.db.count("SMS Queue", {"status": "Received"})
        self.assertEqual(count_after, count_before)


class TestIncomingCanonicalFields(SMSRelayTestCase):
    """Canonical Android SMS Gateway fields (sender/simNumber/receivedAt)."""

    def test_creates_queue_with_canonical_fields(self):
        count_before = frappe.db.count("SMS Queue", {"status": "Received"})
        _handle_incoming_sms({
            "messageId": "m-1",
            "sender": "+15551234567",
            "recipient": "+15559999999",
            "simNumber": 2,
            "message": "Hello",
            "receivedAt": "2026-08-01T09:00:00Z",
            "phoneNumber": "+15551234567",
        }, "sms:received")
        count_after = frappe.db.count("SMS Queue", {"status": "Received"})
        self.assertGreater(count_after, count_before)


class TestDataSmsAndMms(SMSRelayTestCase):
    """Test sms:data-received and MMS webhook events."""

    def test_data_sms(self):
        count_before = frappe.db.count("SMS Queue", {"status": "Received"})
        _handle_incoming_sms({
            "sender": "+15551234567",
            "data": "raw-binary",
            "simNumber": 1,
        }, "sms:data-received")
        count_after = frappe.db.count("SMS Queue", {"status": "Received"})
        self.assertGreater(count_after, count_before)

    def test_mms_received(self):
        _handle_incoming_sms({
            "sender": "+15551234567",
            "subject": "Hi",
            "size": 1024,
        }, "mms:received")
        last = frappe.db.get_value(
            "SMS Queue", {"status": "Received"}, "message", order_by="creation desc"
        )
        self.assertTrue(last)
        self.assertIn("Hi", last)

    def test_mms_downloaded_attachments(self):
        _handle_incoming_sms({
            "sender": "+15551234567",
            "body": "Body text",
            "attachments": [
                {"partId": 1, "contentType": "image/jpeg", "name": "photo.jpg"},
            ],
        }, "mms:downloaded")
        last = frappe.db.get_value(
            "SMS Queue", {"status": "Received"}, "message", order_by="creation desc"
        )
        self.assertTrue(last)
        self.assertIn("photo.jpg", last)


class TestAppStarted(SMSRelayTestCase):
    """Test app:started webhook updates the SMS Device."""

    def test_updates_device(self):
        if frappe.db.exists("SMS Device", "Test App Device"):
            frappe.db.sql("DELETE FROM `tabSMS Device` WHERE name = %s", "Test App Device")
        dev = frappe.new_doc("SMS Device")
        dev.device_name = "Test App Device"
        dev.device_id = "app-device-1"
        dev.sim_number = 1
        dev.is_active = 1
        dev.insert(ignore_permissions=True)
        frappe.db.commit()

        _handle_app_started({
            "event": "app:started",
            "deviceId": "app-device-1",
            "simCards": [
                {"slotIndex": 0, "simNumber": 1, "phoneNumber": "+15551234567", "carrierName": "Test Carrier", "iccid": "iccid-1"},
            ],
        })
        dev.reload()
        self.assertEqual(dev.sim_phone_number, "+15551234567")
        self.assertEqual(dev.carrier_name, "Test Carrier")
        self.assertTrue(dev.is_online)
        self.assertTrue(dev.last_heartbeat)

    def test_unknown_device_ignored(self):
        _handle_app_started({
            "deviceId": "does-not-exist",
            "simCards": [{"simNumber": 1, "phoneNumber": "+15551234567"}],
        })


class TestDeliveryReportFidelity(SMSRelayTestCase):
    """Test delivery reports capture failure reason and parts count."""

    def test_failed_reason(self):
        frappe.get_doc({
            "doctype": "SMS Log",
            "phone": "+15551234567",
            "message": "Test",
            "status": "Sent",
            "gateway_message_id": "gw-fail-1",
            "delivery_status": "Pending",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        _handle_delivery_report({"id": "gw-fail-1", "reason": "Timeout"}, "sms:failed")
        log_name = frappe.db.get_value("SMS Log", {"gateway_message_id": "gw-fail-1"}, "name")
        log = frappe.get_doc("SMS Log", log_name)
        self.assertEqual(log.delivery_status, "Failed")
        self.assertEqual(log.error_message, "Timeout")

    def test_sent_parts(self):
        frappe.get_doc({
            "doctype": "SMS Log",
            "phone": "+15551234567",
            "message": "Test",
            "status": "Queued",
            "gateway_message_id": "gw-sent-1",
            "delivery_status": "Pending",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        _handle_delivery_report({"id": "gw-sent-1", "partsCount": 2}, "sms:sent")
        log_name = frappe.db.get_value("SMS Log", {"gateway_message_id": "gw-sent-1"}, "name")
        log = frappe.get_doc("SMS Log", log_name)
        self.assertEqual(log.delivery_status, "Sent")
        self.assertEqual(log.sms_parts, 2)


class TestWebhookDeliveryQueue(SMSRelayTestCase):
    """Test webhook delivery queue creation."""

    def test_creates_delivery_entry(self):
        count_before = frappe.db.count("SMS Webhook Delivery", {"status": "Pending"})
        _enqueue_webhook_delivery(
            "http://example.com/webhook",
            {"event": "test"},
            {"Content-Type": "application/json"},
        )
        count_after = frappe.db.count("SMS Webhook Delivery", {"status": "Pending"})
        self.assertGreater(count_after, count_before)
