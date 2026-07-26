import frappe
from frappe.utils import cint, cstr, fmt_money, formatdate, nowdate

def money(value, currency=None):
    if not value:
        return "0.00"
    if not currency:
        currency = frappe.defaults.get_global_default("currency") or "USD"
    return fmt_money(value, currency=currency)

def date_fmt(value, fmt="%d-%m-%Y"):
    if not value:
        return ""
    return formatdate(value, fmt)

def phone_fmt(value):
    from sms_relay.core.sms_utils import format_for_display
    return format_for_display(value) if value else ""

def sms_count(value):
    from sms_relay.core.sms_utils import count_sms_parts
    if not value:
        return "0/1 SMS"
    result = count_sms_parts(value)
    return "{}/{} SMS ({})".format(result["parts"], result["parts"], result["encoding"])

def pluralize(count, singular, plural=None):
    if plural is None:
        plural = singular + "s"
    return singular if cint(count) == 1 else plural

def clean_phone_filter(value):
    from sms_relay.core.sms_utils import clean_phone
    return clean_phone(value) if value else ""

def get_methods():
    return {
        "money": money,
        "date_fmt": date_fmt,
        "phone_fmt": phone_fmt,
        "sms_count": sms_count,
        "pluralize": pluralize,
        "clean_phone": clean_phone_filter,
    }

def get_filters():
    return {
        "money": money,
        "date_fmt": date_fmt,
        "phone_fmt": phone_fmt,
        "sms_count": sms_count,
        "pluralize": pluralize,
        "clean_phone": clean_phone_filter,
    }
