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

    def _invoice_doc(self, name, language=None, contact_mobile=None):
        return frappe._dict({
            "doctype": "Sales Invoice",
            "name": name,
            "customer": "Faissal Mannaa",
            "due_date": "2026-07-10",
            "outstanding_amount": 10000.0,
            "language": language,
            "contact_mobile": contact_mobile,
            "as_dict": lambda: {
                "doctype": "Sales Invoice",
                "name": name,
                "customer": "Faissal Mannaa",
                "due_date": "2026-07-10",
                "outstanding_amount": 10000.0,
                "language": language,
                "contact_mobile": contact_mobile,
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


class TestDoctypeEventLocalization(SMSRelayTestCase):
    """DocType Event notifications resolve the phone field and pick an Arabic template variant."""

    def setUp(self):
        super().setUp()
        self._create_templates()
        self._create_notification()

    def _create_templates(self):
        for name, lang, body in [
            (
                "Order Confirmation",
                "en",
                "Thank you for your order {{ doc.name }}. Total: {{ frappe.utils.fmt_money(doc.grand_total) }}. We will process your order shortly.",
            ),
            (
                "Order Confirmation (Arabic)",
                "ar",
                "شكراً لطلبك {{ doc.name }}. الإجمالي: {{ frappe.utils.fmt_money(doc.grand_total) }}. سنقوم بمعالجة طلبك قريباً.",
            ),
        ]:
            if not frappe.db.exists("SMS Template", name):
                tmpl = frappe.new_doc("SMS Template")
                tmpl.template_name = name
                tmpl.category = "TRANSACTIONAL"
                tmpl.language = lang
                tmpl.message_template = body
                tmpl.insert(ignore_permissions=True)

    def _create_notification(self):
        if not frappe.db.exists("SMS Notification", "Order Confirmation Test"):
            n = frappe.new_doc("SMS Notification")
            n.notification_name = "Order Confirmation Test"
            n.notification_type = "DocType Event"
            n.reference_doctype = "Sales Invoice"
            n.doctype_event = "After Submit"
            n.field_name = "contact_mobile"
            n.template = "Order Confirmation"
            n.template_type = "Jinja"
            n.disabled = 0
            n.insert(ignore_permissions=True)

    def _language_patch(self, code):
        real_get_value = frappe.db.get_value

        def fake_get_value(doctype, name, fieldname, *args, **kwargs):
            if doctype == "Language" and fieldname == "language_code":
                return code
            return real_get_value(doctype, name, fieldname, *args, **kwargs)

        return patch("frappe.db.get_value", side_effect=fake_get_value)

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    def test_resolves_phone_from_field(self, mock_enqueue):
        notification = frappe.get_doc("SMS Notification", "Order Confirmation Test")
        doc = self._invoice_doc("ACC-SINV-2026-00033", language="en", contact_mobile="+967777715787")

        with self._language_patch("en"):
            notification.send_template_message(doc)

        mock_enqueue.assert_called_once()
        self.assertEqual(mock_enqueue.call_args.kwargs["phone"], "+967777715787")
        self.assertEqual(mock_enqueue.call_args.kwargs["template"], "Order Confirmation")

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    def test_selects_arabic_template_for_arabic_doc(self, mock_enqueue):
        notification = frappe.get_doc("SMS Notification", "Order Confirmation Test")
        doc = self._invoice_doc("ACC-SINV-2026-00033", language="ar", contact_mobile="+967777715787")

        with self._language_patch("ar"):
            notification.send_template_message(doc)

        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        self.assertIn("شكراً", kwargs["message"])
        self.assertEqual(kwargs["template"], "Order Confirmation (Arabic)")

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    def test_falls_back_to_configured_template_when_no_language(self, mock_enqueue):
        notification = frappe.get_doc("SMS Notification", "Order Confirmation Test")
        doc = self._invoice_doc("ACC-SINV-2026-00033", language=None, contact_mobile="+967777715787")

        with self._language_patch("en"):
            notification.send_template_message(doc)

        mock_enqueue.assert_called_once()
        self.assertEqual(mock_enqueue.call_args.kwargs["template"], "Order Confirmation")
        self.assertIn("Thank you", mock_enqueue.call_args.kwargs["message"])


class TestConditionGating(SMSRelayTestCase):
    """The DocType Event Condition (Python Expression) gates the send."""

    CONDITION = (
        "(doc.outstanding_amount or 0) > 0 "
        "and doc.due_date "
        "and frappe.utils.getdate(doc.due_date) < frappe.utils.getdate()"
    )

    def setUp(self):
        super().setUp()
        self._create_template()
        self._create_notification()

    def _create_template(self):
        if not frappe.db.exists("SMS Template", "Overdue Invoice Reminder"):
            tmpl = frappe.new_doc("SMS Template")
            tmpl.template_name = "Overdue Invoice Reminder"
            tmpl.category = "UTILITY"
            tmpl.language = "en"
            tmpl.message_template = "Dear {{ doc.customer }} - Invoice {{ doc.name }} is overdue."
            tmpl.insert(ignore_permissions=True)

    def _create_notification(self):
        if not frappe.db.exists("SMS Notification", "Overdue Condition Test"):
            n = frappe.new_doc("SMS Notification")
            n.notification_name = "Overdue Condition Test"
            n.notification_type = "DocType Event"
            n.reference_doctype = "Sales Invoice"
            n.doctype_event = "After Submit"
            n.field_name = "contact_mobile"
            n.template = "Overdue Invoice Reminder"
            n.template_type = "Jinja"
            n.condition = self.CONDITION
            n.disabled = 0
            n.insert(ignore_permissions=True)

    def _invoice_doc(self, outstanding=10000.0, due_date="2026-07-10", contact_mobile="+967777715787"):
        data = frappe._dict({
            "doctype": "Sales Invoice",
            "name": "ACC-SINV-2026-00033",
            "customer": "Faissal Mannaa",
            "due_date": due_date,
            "outstanding_amount": outstanding,
            "contact_mobile": contact_mobile,
        })
        data.as_dict = lambda: data
        return data

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    def test_sends_when_overdue(self, mock_enqueue):
        notification = frappe.get_doc("SMS Notification", "Overdue Condition Test")
        notification.send_template_message(self._invoice_doc())

        mock_enqueue.assert_called_once()
        self.assertEqual(mock_enqueue.call_args.kwargs["phone"], "+967777715787")

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    def test_skips_when_fully_paid(self, mock_enqueue):
        notification = frappe.get_doc("SMS Notification", "Overdue Condition Test")
        notification.send_template_message(self._invoice_doc(outstanding=0.0))

        mock_enqueue.assert_not_called()

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    def test_skips_when_not_yet_due(self, mock_enqueue):
        notification = frappe.get_doc("SMS Notification", "Overdue Condition Test")
        notification.send_template_message(self._invoice_doc(due_date="2026-12-31"))

        mock_enqueue.assert_not_called()

    @patch("sms_relay.core.sms_engine._enqueue_sms")
    def test_skips_when_no_due_date_without_error(self, mock_enqueue):
        notification = frappe.get_doc("SMS Notification", "Overdue Condition Test")
        notification.send_template_message(self._invoice_doc(due_date=None))

        mock_enqueue.assert_not_called()
