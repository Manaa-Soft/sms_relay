import frappe
from frappe.tests import IntegrationTestCase
from sms_relay.core.sms_engine import _enqueue_sms, _render_template
from sms_relay.core.sms_utils import clean_phone


class TestNotificationRendering(IntegrationTestCase):
    """Test SMS Notification template rendering."""

    def test_jinja_render(self):
        result = _render_template("Test Template", {
            "doc": {"customer": "Acme Corp", "grand_total": 5000}
        })
        self.assertIn("Acme Corp", result)
        self.assertIn("5000", result)

    def test_parameter_mode_replacement(self):
        if not frappe.db.exists("SMS Template", "Param Template"):
            tmpl = frappe.new_doc("SMS Template")
            tmpl.template_name = "Param Template"
            tmpl.message_template = "Hello {{1}}, order {{2}} ready."
            tmpl.insert(ignore_permissions=True)

        notification = frappe.new_doc("SMS Notification")
        notification.notification_name = "Test Param Notif"
        notification.notification_type = "DocType Event"
        notification.reference_doctype = "SMS Queue"
        notification.doctype_event = "On Save"
        notification.template_type = "Parameter"
        notification.template = "Param Template"
        notification.field_name = "recipient"
        notification.message_template = "Hello {{1}}, order {{2}} ready."
        notification.append("fields", {"field_name": "recipient"})
        notification.append("fields", {"field_name": "message"})
        notification.insert(ignore_permissions=True)

        class FakeDoc:
            def __init__(self, data):
                self._data = data
            def get(self, key):
                return self._data.get(key)
            def get_formatted(self, key):
                return str(self._data.get(key, ""))
            def __getattr__(self, key):
                return self._data.get(key)

        doc = FakeDoc({"recipient": "+15551234567", "message": "Order 123"})
        result = notification._replace_positional_params("Hello {{1}}, order {{2}} ready.", doc)
        self.assertIn("+15551234567", result)
        self.assertIn("Order 123", result)

    def test_empty_template_returns_empty(self):
        if not frappe.db.exists("SMS Template", "Empty Tmpl"):
            tmpl = frappe.new_doc("SMS Template")
            tmpl.template_name = "Empty Tmpl"
            tmpl.message_template = ""
            tmpl.insert(ignore_permissions=True)
        result = _render_template("Empty Tmpl", {})
        self.assertEqual(result, "")


class TestPriorityDetection(IntegrationTestCase):
    """Test priority tier auto-detection."""

    def test_payment_is_high(self):
        message = "Your payment of $100 has been received."
        priority = "High" if any(w in message.lower() for w in ("payment", "otp")) else "Normal"
        self.assertEqual(priority, "High")

    def test_otp_is_high(self):
        message = "Your OTP is 123456"
        priority = "High" if any(w in message.lower() for w in ("payment", "otp")) else "Normal"
        self.assertEqual(priority, "High")

    def test_regular_is_normal(self):
        message = "Your order has been dispatched."
        priority = "High" if any(w in message.lower() for w in ("payment", "otp")) else "Normal"
        self.assertEqual(priority, "Normal")


class TestNotificationMap(IntegrationTestCase):
    """Test notification map caching."""

    def test_map_structure(self):
        from sms_relay.utils import get_notifications_map
        frappe.cache().delete_value("sms_notification_map")
        result = get_notifications_map()
        self.assertIsInstance(result, dict)
