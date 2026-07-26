import re
import hashlib
import hmac
import frappe
from frappe.utils import cint

GSM7_CHARS = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "ÄÖÑÜ¿abcdefghijklmnopqrstuvwxyz"
    "äöñüà"
)

GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "äöñüà"
)

SINGLE_SMS_GSM7 = 160
SINGLE_SMS_UNICODE = 70
MULTIPART_GSM7 = 153
MULTIPART_UNICODE = 67

PHONE_CLEAN_RE = re.compile(r"[^\d+]")

def clean_phone(phone):
    if not phone:
        return ""
    cleaned = PHONE_CLEAN_RE.sub("", str(phone).strip())
    if cleaned and not cleaned.startswith("+"):
        if len(cleaned) == 10:
            cleaned = "+1" + cleaned
        elif len(cleaned) == 11 and cleaned.startswith("1"):
            cleaned = "+" + cleaned
        elif len(cleaned) >= 7:
            cleaned = "+" + cleaned
    return cleaned

def format_for_display(phone):
    cleaned = clean_phone(phone)
    if not cleaned:
        return phone or ""
    if cleaned.startswith("+1") and len(cleaned) == 12:
        return "({}) {}-{}".format(cleaned[2:5], cleaned[5:8], cleaned[8:])
    return cleaned

def is_gsm7(text):
    if not text:
        return True
    return all(c in GSM7_CHARS for c in text)

def count_sms_parts(text, encoding="auto"):
    if not text:
        return {"parts": 0, "encoding": "GSM-7", "chars": 0, "max_chars": SINGLE_SMS_GSM7}

    if encoding == "auto":
        use_gsm7 = is_gsm7(text)
    else:
        use_gsm7 = encoding == "gsm7"

    chars = len(text)

    if use_gsm7:
        if chars <= SINGLE_SMS_GSM7:
            return {"parts": 1, "encoding": "GSM-7", "chars": chars, "max_chars": SINGLE_SMS_GSM7}
        parts = (chars + MULTIPART_GSM7 - 1) // MULTIPART_GSM7
        return {"parts": parts, "encoding": "GSM-7", "chars": chars, "max_chars": MULTIPART_GSM7}
    else:
        if chars <= SINGLE_SMS_UNICODE:
            return {"parts": 1, "encoding": "Unicode", "chars": chars, "max_chars": SINGLE_SMS_UNICODE}
        parts = (chars + MULTIPART_UNICODE - 1) // MULTIPART_UNICODE
        return {"parts": parts, "encoding": "Unicode", "chars": chars, "max_chars": MULTIPART_UNICODE}

def verify_webhook_signature(payload_bytes, secret, signature):
    if not secret or not signature:
        return False
    try:
        expected = hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False

def get_relay_settings():
    cached = frappe.cache().get_value("sms_relay_settings")
    if cached is not None:
        return cached
    settings = frappe.get_single("SMS Gateway Settings")
    frappe.cache().set_value("sms_relay_settings", settings, timeout=300)
    return settings

def get_opted_out_numbers():
    cached = frappe.cache().get_value("sms_opted_out_numbers")
    if cached is not None:
        return cached
    numbers = frappe.get_all(
        "SMS Opt Out",
        filters={"opted_out": 1},
        pluck="phone",
    )
    frappe.cache().set_value("sms_opted_out_numbers", numbers, timeout=600)
    return numbers

def is_opted_out(phone):
    cleaned = clean_phone(phone)
    numbers = get_opted_out_numbers()
    return cleaned in numbers or phone in numbers

def get_communication_medium():
    return "SMS"

def validate_phone_list(phone_list):
    valid = []
    for phone in phone_list:
        cleaned = clean_phone(phone)
        if cleaned and len(cleaned) >= 7:
            valid.append(cleaned)
    return valid
