import frappe
from unittest.mock import patch
from sms_relay.tests.conftest import SMSRelayTestCase
from sms_relay.core.bulk_engine import (
    create_bulk_job,
    process_bulk_job,
    _load_csv_recipients,
    _resolve_message,
)


class TestCreateBulkJob(SMSRelayTestCase):
    """Test bulk job creation."""

    def test_create_text_bulk(self):
        csv_data = "phone,name\n+15551111111,John\n+15552222222,Jane"
        bulk = create_bulk_job(
            message_type="Text",
            message="Hello bulk",
            recipients_csv=csv_data,
        )
        self.assertEqual(bulk.status, "Draft")
        self.assertEqual(bulk.total_recipients, 2)
        self.assertEqual(bulk.message, "Hello bulk")

    def test_create_template_bulk(self):
        bulk = create_bulk_job(
            message_type="Template",
            template="Test Template",
            recipients_csv="phone\n+15551111111",
        )
        self.assertEqual(bulk.status, "Draft")
        self.assertEqual(bulk.total_recipients, 1)

    def test_create_no_message_throws(self):
        with self.assertRaises(frappe.ValidationError):
            create_bulk_job(message_type="Text")

    def test_create_no_template_throws(self):
        with self.assertRaises(frappe.ValidationError):
            create_bulk_job(message_type="Template")


class TestLoadCsvRecipients(SMSRelayTestCase):
    """Test CSV parsing."""

    def test_standard_csv(self):
        bulk = frappe.new_doc("SMS Bulk Message")
        bulk.message_type = "Text"
        bulk.message = "Test"
        csv_data = "phone,name\n+15551111111,John\n+15552222222,Jane"
        _load_csv_recipients(bulk, csv_data)
        self.assertEqual(len(bulk.recipients), 2)
        self.assertEqual(bulk.recipients[0].phone, "+15551111111")

    def test_alt_column_names(self):
        bulk = frappe.new_doc("SMS Bulk Message")
        bulk.message_type = "Text"
        bulk.message = "Test"
        csv_data = "mobile,recipient_name\n+15551111111,John"
        _load_csv_recipients(bulk, csv_data)
        self.assertEqual(len(bulk.recipients), 1)


class TestProcessBulkJob(SMSRelayTestCase):
    """Test bulk job processing."""

    @patch("sms_relay.core.sms_engine._send_to_device")
    def test_processes_batch(self, mock_send):
        mock_send.return_value = {"success": True, "message_id": "gw-001"}
        csv_data = "phone,name\n+15551111111,John\n+15552222222,Jane\n+15553333333,Bob"
        bulk = create_bulk_job(
            message_type="Text",
            message="Bulk test",
            recipients_csv=csv_data,
        )
        frappe.db.commit()

        process_bulk_job(bulk.name)
        bulk.reload()
        self.assertIn(bulk.status, ("Processing", "Completed"))
        self.assertGreater(bulk.sent_count, 0)

    @patch("sms_relay.core.sms_engine._send_to_device")
    def test_completes_when_all_sent(self, mock_send):
        mock_send.return_value = {"success": True, "message_id": "gw-001"}
        csv_data = "phone\n+15551111111"
        bulk = create_bulk_job(
            message_type="Text",
            message="Single",
            recipients_csv=csv_data,
        )
        frappe.db.commit()

        process_bulk_job(bulk.name)
        bulk.reload()
        self.assertEqual(bulk.status, "Completed")


class TestResolveMessage(SMSRelayTestCase):
    """Test message resolution."""

    def test_text_type(self):
        bulk = frappe.new_doc("SMS Bulk Message")
        bulk.message_type = "Text"
        bulk.message = "Direct message"
        result = _resolve_message(bulk, "+15551234567")
        self.assertEqual(result, "Direct message")

    def test_template_type(self):
        tmpl = frappe.new_doc("SMS Template")
        tmpl.template_name = "Bulk Simple"
        tmpl.category = "UTILITY"
        tmpl.language = "en"
        tmpl.message_template = "Hello, order is ready for pickup."
        tmpl.insert(ignore_permissions=True)
        bulk = frappe.new_doc("SMS Bulk Message")
        bulk.message_type = "Template"
        bulk.template = "Bulk Simple"
        result = _resolve_message(bulk, "+15551234567")
        self.assertIsNotNone(result)
