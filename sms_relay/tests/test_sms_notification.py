import frappe
from unittest.mock import patch
from sms_relay.tests.conftest import SMSRelayTestCase


class TestSchedulerOverdueInvoices(SMSRelayTestCase):
    """Scheduler Event SMS Notification with Scheduler Data Source = Overdue Invoices."""

    def setUp(self):
        super().setUp()
        self._create_overdue_templates()
        self._create_overdue_notification()

    def _create_overdue_templates(self):
        for name, lang, body in [
            (
                "Overdue Invoice Reminder",
                "en",
                "Dear {{ doc.customer }} - Reminder: Invoice {{ doc.name }} is overdue "
                "(due {{ frappe.utils.formatdate(doc.due_date) }}). Outstanding: "
                "{{ frappe.utils.fmt_money(doc.outstanding_amount) }}. Please pay soon.",
            ),
            (
                "Overdue Invoice Reminder (Arabic)",
                "ar",
                "عزيزي {{ doc.customer }}، تذكير: الفاتورة {{ doc.name }} متأخرة السداد "
                "(تاريخ الاستحقاق {{ frappe.utils.formatdate(doc.due_date) }}). "
                "المبلغ المستحق: {{ frappe.utils.fmt_money(doc.outstanding_amount) }}. "
                "يرجى الدفع في أقرب وقت.",
            ),
        ]:
            if not frappe.db.exists("SMS Template", name):
                tmpl = frappe.new_doc("SMS Template")
                tmpl.template_name = name
                tmpl.category = "UTILITY"
                tmpl.language = lang
                tmpl.message_template = body
                tmpl.insert(ignore_permissions=True)

    def _create_overdue_notification(self):
        if not frappe.db.exists("SMS Notification", "Overdue Reminder Test"):
            n = frappe.new_doc("SMS Notification")
            n.notification_name = "Overdue Reminder Test"
            n.notification_type = "Scheduler Event"
            n.reference_doctype = "Sales Invoice"
            n.event_frequency = "Daily"
            n.scheduler_data_source = "Overdue Invoices"
            n.template = "Overdue Invoice Reminder"
            n.template_type = "Jinja"
            n.disabled = 0
            n.insert(ignore_permissions=True)

    def _invoice_doc(self, name):
        return frappe._dict({
            "doctype": "Sales Invoice",
            "name": name,
            "customer": "Faissal Mannaa",
            "due_date": "2026-07-10",
            "outstanding_amount": 10000.0,
            "as_dict": lambda: {
                "doctype": "Sales Invoice",
                "name": name,
                "customer": "Faissal Mannaa",
                "due_date": "2026-07-10",
                "outstanding_amount": 10000.0,
            },
        })

    def _run_notification(self, invoices, language_code):
        real_get_doc = frappe.get_doc
        real_get_value = frappe.db.get_value

        def fake_get_doc(doctype, name=None, *args, **kwargs):
            if doctype == "Sales Invoice":
                return self._invoice_doc(name)
            return real_get_doc(doctype, name, *args, **kwargs)

        def fake_get_value(doctype, name, fieldname, *args, **kwargs):
            if doctype == "Sales Invoice" and fieldname == "language":
                return language_code
            if doctype == "Language" and fieldname == "language_code":
                return language_code
            return real_get_value(doctype, name, fieldname, *args, **kwargs)

        notification = frappe.get_doc("SMS Notification", "Overdue Reminder Test")
        with patch("frappe.get_all", return_value=invoices), \
                patch("frappe.get_doc", side_effect=fake_get_doc), \
                patch("frappe.db.get_value", side_effect=fake_get_value):
            notification.send_scheduled_message()

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    @patch("sms_relay.core.sms_engine._get_customer_phone")
    def test_overdue_invoices_enqueue_per_invoice(self, mock_phone, mock_enqueue):
        mock_phone.return_value = "+967777715787"
        invoices = [frappe._dict({
            "name": "ACC-SINV-2026-00033",
            "customer": "Faissal Mannaa",
        })]

        self._run_notification(invoices, language_code="en")

        mock_phone.assert_called_once_with("Faissal Mannaa")
        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        self.assertIn("ACC-SINV-2026-00033", kwargs["message"])
        self.assertIn("Faissal Mannaa", kwargs["message"])
        self.assertIn("10,000.00", kwargs["message"])
        self.assertEqual(kwargs["template"], "Overdue Invoice Reminder")
        self.assertEqual(kwargs["reference_doctype"], "Sales Invoice")
        self.assertEqual(kwargs["reference_name"], "ACC-SINV-2026-00033")

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    @patch("sms_relay.core.sms_engine._get_customer_phone")
    def test_overdue_invoices_pick_arabic_template(self, mock_phone, mock_enqueue):
        mock_phone.return_value = "+967777715787"
        invoices = [frappe._dict({
            "name": "ACC-SINV-2026-00033",
            "customer": "Faissal Mannaa",
        })]

        self._run_notification(invoices, language_code="ar")

        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        self.assertIn("عزيزي", kwargs["message"])
        self.assertEqual(kwargs["template"], "Overdue Invoice Reminder (Arabic)")

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    @patch("sms_relay.core.sms_engine._get_customer_phone")
    def test_skips_invoice_without_phone(self, mock_phone, mock_enqueue):
        mock_phone.return_value = None
        invoices = [frappe._dict({
            "name": "ACC-SINV-2026-00033",
            "customer": "Faissal Mannaa",
        })]

        self._run_notification(invoices, language_code="en")

        mock_enqueue.assert_not_called()

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    def test_disabled_notification_sends_nothing(self, mock_enqueue):
        notification = frappe.get_doc("SMS Notification", "Overdue Reminder Test")
        notification.disabled = 1
        notification.send_template_message(self._invoice_doc("ACC-SINV-2026-00033"), "+967777715787")
        mock_enqueue.assert_not_called()
