import json
import frappe
from unittest.mock import patch, MagicMock
from sms_relay.tests.conftest import SMSRelayTestCase
from sms_relay.tasks import (
    process_sms_queue,
    process_scheduled_messages,
    process_outbox,
    process_bulk_messages,
    process_webhook_deliveries,
    send_overdue_reminders,
    _process_queue_item,
    _process_outbox_item,
    _process_webhook_delivery,
    retry_failed_sms,
    reset_daily_quotas,
    cleanup_old_logs,
)


class TestProcessSmsQueue(SMSRelayTestCase):
    """Test SMS queue processing."""

    @patch("sms_relay.core.sms_engine._send_to_device")
    def test_processes_queued_item(self, mock_send):
        mock_send.return_value = {"success": True, "message_id": "gw-001"}
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Queue test"
        queue.status = "Queued"
        queue.device = "Test Phone"
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        process_sms_queue()
        queue.reload()
        self.assertEqual(queue.status, "Sent")

    @patch("sms_relay.core.sms_engine._send_to_device")
    def test_failed_send_stays_queued(self, mock_send):
        mock_send.return_value = {"success": False, "error": "Connection refused"}
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Fail test"
        queue.status = "Queued"
        queue.device = "Test Phone"
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        process_sms_queue()
        queue.reload()
        self.assertIn(queue.status, ["Queued", "Failed"])


class TestProcessScheduledMessages(SMSRelayTestCase):
    """Test scheduled message processing."""

    @patch("sms_relay.core.sms_engine._send_to_device")
    def test_processes_due_message(self, mock_send):
        mock_send.return_value = {"success": True, "message_id": "gw-001"}
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Scheduled test"
        queue.status = "Queued"
        queue.device = "Test Phone"
        queue.scheduled_at = frappe.utils.now_datetime()
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        process_scheduled_messages()
        queue.reload()
        self.assertEqual(queue.status, "Sent")

    def test_skips_future_message(self):
        from frappe.utils import add_to_date
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Future test"
        queue.status = "Queued"
        queue.device = "Test Phone"
        queue.scheduled_at = add_to_date(frappe.utils.now_datetime(), days=1)
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        process_scheduled_messages()
        queue.reload()
        self.assertEqual(queue.status, "Queued")


class TestTtlExpiry(SMSRelayTestCase):
    """Test TTL and valid_until expiry."""

    def test_expired_valid_until(self):
        from frappe.utils import add_to_date
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Expired"
        queue.status = "Queued"
        queue.device = "Test Phone"
        queue.valid_until = add_to_date(frappe.utils.now_datetime(), days=-1)
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        _process_queue_item(queue.name)
        queue.reload()
        self.assertEqual(queue.status, "Failed")

    def test_expired_ttl(self):
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "TTL expired"
        queue.status = "Queued"
        queue.device = "Test Phone"
        queue.ttl_seconds = 1
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        import time
        time.sleep(2)
        _process_queue_item(queue.name)
        queue.reload()
        self.assertEqual(queue.status, "Failed")


class TestSendOverdueReminders(SMSRelayTestCase):
    """Test overdue invoice reminders."""

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    @patch("sms_relay.core.sms_engine._get_customer_phone")
    def test_sends_well_formed_message(self, mock_phone, mock_enqueue):
        mock_phone.return_value = "+967777715787"
        mock_enqueue.return_value = None

        invoices = [{
            "name": "ACC-SINV-2026-00033",
            "customer": "Faissal Mannaa",
            "due_date": "2026-07-10",
            "outstanding_amount": 10000.0,
        }]
        with patch("frappe.get_all", return_value=invoices):
            send_overdue_reminders()

        mock_phone.assert_called_once_with("Faissal Mannaa")
        self.assertEqual(mock_enqueue.call_count, 1)
        msg = mock_enqueue.call_args.kwargs["message"]
        from frappe.utils import formatdate, fmt_money
        self.assertIn("ACC-SINV-2026-00033", msg)
        self.assertIn("Faissal Mannaa", msg)
        self.assertIn(fmt_money(10000.0), msg)
        self.assertIn(formatdate("2026-07-10"), msg)

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    @patch("sms_relay.core.sms_engine._get_customer_phone")
    def test_skips_customer_without_phone(self, mock_phone, mock_enqueue):
        mock_phone.return_value = None

        invoices = [{
            "name": "ACC-SINV-2026-00033",
            "customer": "Faissal Mannaa",
            "due_date": "2026-07-10",
            "outstanding_amount": 10000.0,
        }]
        with patch("frappe.get_all", return_value=invoices):
            send_overdue_reminders()

        mock_enqueue.assert_not_called()

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    @patch("sms_relay.core.sms_engine._get_customer_phone")
    def test_handles_multiple_overdue_invoices(self, mock_phone, mock_enqueue):
        mock_phone.return_value = "+967777715787"

        invoices = [
            {
                "name": "ACC-SINV-2026-00177",
                "customer": "Faissal Mannaa",
                "due_date": "2026-07-19",
                "outstanding_amount": 50.0,
            },
            {
                "name": "ACC-SINV-2026-00033",
                "customer": "Manaa Mannaa",
                "due_date": "2026-07-10",
                "outstanding_amount": 2000.0,
            },
        ]
        with patch("frappe.get_all", return_value=invoices):
            send_overdue_reminders()

        self.assertEqual(mock_enqueue.call_count, 2)


class TestRetryFailedSms(SMSRelayTestCase):
    """Test daily retry job."""

    def test_retries_failed(self):
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Retry me"
        queue.status = "Failed"
        queue.retry_count = 1
        queue.max_retries = 3
        queue.insert(ignore_permissions=True)
        frappe.db.commit()

        retry_failed_sms()
        queue.reload()
        self.assertEqual(queue.status, "Queued")


class TestResetDailyQuotas(SMSRelayTestCase):
    """Test daily quota reset."""

    def test_resets_counters(self):
        frappe.db.set_value("SMS Device", "Test Phone", "sent_today", 50)
        frappe.db.commit()
        reset_daily_quotas()
        frappe.db.commit()
        val = frappe.db.get_value("SMS Device", "Test Phone", "sent_today")
        self.assertEqual(val, 0)


class TestProcessWebhookDeliveries(SMSRelayTestCase):
    """Test webhook delivery processing."""

    @patch("sms_relay.tasks.requests.post")
    def test_successful_delivery(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_post.return_value = mock_resp

        delivery = frappe.new_doc("SMS Webhook Delivery")
        delivery.url = "http://example.com/webhook"
        delivery.payload = json.dumps({"event": "test"})
        delivery.status = "Pending"
        delivery.attempts = 0
        delivery.max_attempts = 15
        delivery.base_delay = 30
        delivery.insert(ignore_permissions=True)
        frappe.db.commit()

        _process_webhook_delivery(delivery.name)
        delivery.reload()
        self.assertEqual(delivery.status, "Sent")

    @patch("sms_relay.tasks.requests.post")
    def test_failed_delivery_retries(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Error"
        mock_post.return_value = mock_resp

        delivery = frappe.new_doc("SMS Webhook Delivery")
        delivery.url = "http://example.com/webhook"
        delivery.payload = json.dumps({"event": "test"})
        delivery.status = "Pending"
        delivery.attempts = 0
        delivery.max_attempts = 15
        delivery.base_delay = 30
        delivery.insert(ignore_permissions=True)
        frappe.db.commit()

        _process_webhook_delivery(delivery.name)
        delivery.reload()
        self.assertEqual(delivery.status, "Pending")
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNotNone(delivery.next_retry_at)

    def test_max_attempts_marks_failed(self):
        delivery = frappe.new_doc("SMS Webhook Delivery")
        delivery.url = "http://example.com/webhook"
        delivery.payload = "{}"
        delivery.status = "Pending"
        delivery.attempts = 15
        delivery.max_attempts = 15
        delivery.base_delay = 30
        delivery.insert(ignore_permissions=True)
        frappe.db.commit()

        _process_webhook_delivery(delivery.name)
        delivery.reload()
        self.assertEqual(delivery.status, "Failed")
