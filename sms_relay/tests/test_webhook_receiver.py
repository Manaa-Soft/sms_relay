import json
import frappe
from unittest.mock import patch, MagicMock
from frappe.tests import IntegrationTestCase
from sms_relay.api.webhook_receiver import (
    incoming_webhook,
    _handle_delivery_report,
    _handle_cancelled_report,
    _handle_incoming_sms,
    _idempotency_check,
    _enqueue_webhook_delivery,
)


class TestIdempotencyCheck(IntegrationTestCase):
    """Test webhook idempotency."""

    def test_first_call_returns_false(self):
        frappe.cache().delete_value("webhook_test_prefix_abc")
        result = _idempotency_check({"test": "abc"}, "test_prefix")
        self.assertFalse(result)

    def test_second_call_returns_true(self):
        frappe.cache().delete_value("webhook_test_prefix_def")
        _idempotency_check({"test": "def"}, "test_prefix")
        result = _idempotency_check({"test": "def"}, "test_prefix")
        self.assertTrue(result)


class TestDeliveryReport(IntegrationTestCase):
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


class TestIncomingSms(IntegrationTestCase):
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


class TestWebhookDeliveryQueue(IntegrationTestCase):
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
