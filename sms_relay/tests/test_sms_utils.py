import frappe
from frappe.tests import IntegrationTestCase
from sms_relay.core.sms_utils import (
    clean_phone,
    count_sms_parts,
    is_gsm7,
    is_opted_out,
    validate_phone_list,
    verify_webhook_signature,
    format_for_display,
)


class TestCleanPhone(IntegrationTestCase):
    """Test phone number normalization to E.164."""

    def test_e164_with_plus(self):
        self.assertEqual(clean_phone("+1234567890"), "+1234567890")

    def test_e164_with_country_code(self):
        self.assertEqual(clean_phone("12345678901"), "+12345678901")

    def test_10_digit_us_number(self):
        result = clean_phone("5551234567")
        self.assertEqual(result, "+15551234567")

    def test_11_digit_starting_with_1(self):
        result = clean_phone("15551234567")
        self.assertEqual(result, "+15551234567")

    def test_international_number(self):
        result = clean_phone("+447911123456")
        self.assertEqual(result, "+447911123456")

    def test_short_number(self):
        result = clean_phone("123456")
        self.assertEqual(result, "+123456")

    def test_empty_input(self):
        self.assertEqual(clean_phone(""), "")

    def test_none_input(self):
        self.assertEqual(clean_phone(None), "")

    def test_strips_special_characters(self):
        result = clean_phone("+1 (555) 123-4567")
        self.assertEqual(result, "+15551234567")

    def test_strips_dashes(self):
        result = clean_phone("+1-555-123-4567")
        self.assertEqual(result, "+15551234567")

    def test_strips_spaces(self):
        result = clean_phone("+1 555 123 4567")
        self.assertEqual(result, "+15551234567")

    def test_leads_with_plus_preserved(self):
        result = clean_phone("+967771234567")
        self.assertTrue(result.startswith("+"))


class TestCountSmsParts(IntegrationTestCase):
    """Test SMS character counting and segment calculation."""

    def test_empty_text(self):
        result = count_sms_parts("")
        self.assertEqual(result["parts"], 0)

    def test_gsm7_single_part(self):
        result = count_sms_parts("Hello World")
        self.assertEqual(result["parts"], 1)
        self.assertEqual(result["encoding"], "GSM-7")
        self.assertEqual(result["chars"], 11)
        self.assertEqual(result["max_chars"], 160)

    def test_gsm7_exactly_160(self):
        text = "A" * 160
        result = count_sms_parts(text)
        self.assertEqual(result["parts"], 1)
        self.assertEqual(result["encoding"], "GSM-7")

    def test_gsm7_multi_part(self):
        text = "A" * 161
        result = count_sms_parts(text)
        self.assertEqual(result["parts"], 2)
        self.assertEqual(result["encoding"], "GSM-7")
        self.assertEqual(result["max_chars"], 153)

    def test_unicode_single_part(self):
        text = "Hello \u00e9\u00e8\u00ea"
        result = count_sms_parts(text)
        self.assertEqual(result["parts"], 1)
        self.assertEqual(result["encoding"], "Unicode")
        self.assertEqual(result["max_chars"], 70)

    def test_unicode_multi_part(self):
        text = "\u00e9" * 71
        result = count_sms_parts(text)
        self.assertEqual(result["parts"], 2)
        self.assertEqual(result["encoding"], "Unicode")
        self.assertEqual(result["max_chars"], 67)

    def test_auto_detect_gsm7(self):
        result = count_sms_parts("Test", encoding="auto")
        self.assertEqual(result["encoding"], "GSM-7")

    def test_auto_detect_unicode(self):
        result = count_sms_parts("\u4f60\u597d\u4e16\u754c", encoding="auto")
        self.assertEqual(result["encoding"], "Unicode")


class TestIsGsm7(IntegrationTestCase):
    """Test GSM-7 character detection."""

    def test_basic_ascii(self):
        self.assertTrue(is_gsm7("Hello"))

    def test_unicode_char(self):
        self.assertFalse(is_gsm7("\u00e9"))

    def test_empty(self):
        self.assertTrue(is_gsm7(""))

    def test_none(self):
        self.assertTrue(is_gsm7(None))


class TestOptOut(IntegrationTestCase):
    """Test opt-out checking."""

    def test_not_opted_out(self):
        self.assertFalse(is_opted_out("+15551234567"))

    def test_opted_out(self):
        phone = "+15559999999"
        frappe.get_doc({
            "doctype": "SMS Opt Out",
            "phone": phone,
            "opted_out": 1,
            "reason": "Test",
            "source": "Manual",
        }).insert(ignore_permissions=True)
        frappe.cache().delete_value("sms_opted_out_numbers")
        self.assertTrue(is_opted_out(phone))

    def test_opted_out_cleared(self):
        phone = "+15558888888"
        opt = frappe.get_doc({
            "doctype": "SMS Opt Out",
            "phone": phone,
            "opted_out": 1,
            "reason": "Test",
            "source": "Manual",
        })
        opt.insert(ignore_permissions=True)
        frappe.cache().delete_value("sms_opted_out_numbers")
        self.assertTrue(is_opted_out(phone))
        frappe.delete_doc("SMS Opt Out", opt.name)
        frappe.cache().delete_value("sms_opted_out_numbers")
        self.assertFalse(is_opted_out(phone))


class TestValidatePhoneList(IntegrationTestCase):
    """Test phone list validation."""

    def test_valid_numbers(self):
        result = validate_phone_list(["+15551234567", "+447911123456"])
        self.assertEqual(len(result), 2)

    def test_filters_invalid(self):
        result = validate_phone_list(["+15551234567", "abc", ""])
        self.assertEqual(len(result), 1)

    def test_normalizes(self):
        result = validate_phone_list(["(555) 123-4567"])
        self.assertEqual(result[0], "+15551234567")


class TestVerifyWebhookSignature(IntegrationTestCase):
    """Test HMAC-SHA256 webhook signature verification."""

    def test_valid_signature(self):
        import hmac
        import hashlib
        secret = "test-secret"
        payload = b'{"event": "sms:delivered"}'
        sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(payload, secret, sig))

    def test_invalid_signature(self):
        self.assertFalse(verify_webhook_signature(b"data", "secret", "bad-sig"))

    def test_empty_secret(self):
        self.assertFalse(verify_webhook_signature(b"data", "", "sig"))

    def test_empty_signature(self):
        self.assertFalse(verify_webhook_signature(b"data", "secret", ""))


class TestFormatForDisplay(IntegrationTestCase):
    """Test phone formatting for display."""

    def test_us_number(self):
        result = format_for_display("+15551234567")
        self.assertEqual(result, "(555) 123-4567")

    def test_international(self):
        result = format_for_display("+447911123456")
        self.assertEqual(result, "+447911123456")

    def test_empty(self):
        self.assertEqual(format_for_display(""), "")
