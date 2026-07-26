import frappe
from frappe.utils import cstr

def ensure_contact(phone, profile_name=None):
    from sms_relay.core.sms_utils import clean_phone
    cleaned = clean_phone(phone)
    if not cleaned:
        return None

    existing = frappe.db.get_value(
        "Contact",
        {"phone": ["like", "%{}".format(cleaned[-8:])]},
        "name",
    )
    if existing:
        return existing

    contact = frappe.new_doc("Contact")
    contact.first_name = profile_name or cleaned
    contact.append("phone_nos", {"phone": cleaned, "is_primary_mobile_no": 1})
    contact.insert(ignore_permissions=True)
    return contact.name

def ensure_lead(phone, profile_name=None):
    from sms_relay.core.sms_utils import clean_phone
    cleaned = clean_phone(phone)
    if not cleaned:
        return None

    existing = frappe.db.get_value(
        "Lead",
        {"phone": ["like", "%{}".format(cleaned[-8:])]},
        "name",
    )
    if existing:
        return existing

    lead = frappe.new_doc("Lead")
    lead.lead_name = profile_name or cleaned
    lead.phone = cleaned
    lead.mobile_no = cleaned
    lead.source = "SMS"
    lead.insert(ignore_permissions=True)
    return lead.name

def create_communication(message_doc, phone, profile_name=None):
    from sms_relay.core.sms_utils import clean_phone
    cleaned = clean_phone(phone)

    contact_name = ensure_contact(cleaned, profile_name)

    communication = frappe.new_doc("Communication")
    communication.communication_type = "Communication"
    communication.communication_medium = "SMS"
    communication.sent_or_received = "Received"
    communication.phone_no = cleaned
    communication.content = message_doc.get("message", "") if isinstance(message_doc, dict) else getattr(message_doc, "message", "")
    communication.subject = "SMS from {}".format(cleaned)
    if contact_name:
        communication.reference_doctype = "Contact"
        communication.reference_name = contact_name
    communication.insert(ignore_permissions=True)
    return communication.name

def find_existing_lead(phone):
    from sms_relay.core.sms_utils import clean_phone
    cleaned = clean_phone(phone)
    if not cleaned:
        return None
    return frappe.db.get_value(
        "Lead",
        {"phone": ["like", "%{}".format(cleaned[-8:])]},
        "name",
    )

def find_existing_contact(phone):
    from sms_relay.core.sms_utils import clean_phone
    cleaned = clean_phone(phone)
    if not cleaned:
        return None
    return frappe.db.get_value(
        "Contact",
        {"phone": ["like", "%{}".format(cleaned[-8:])]},
        "name",
    )
