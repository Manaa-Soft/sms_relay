import frappe
from frappe import _
from frappe.utils import fmt_money, getdate, nowdate

from sms_relay.sms_engine import (
    _get_customer_phone,
    _enqueue_sms,
    _check_opt_out,
    _get_gateway_config,
    _render_template,
)


def on_invoice_submit(doc, method):
    """Sales Invoice on_submit hook – sends invoice notification SMS."""
    config = _get_gateway_config()
    if not config.get("send_invoice_sms"):
        return

    if doc.doctype != "Sales Invoice":
        return

    customer = doc.customer
    if not customer:
        return

    phone = _get_customer_phone(customer)
    if not phone:
        frappe.msgprint(_("No phone number found for customer {0}").format(customer))
        return

    if _check_opt_out(phone):
        return

    context = {
        "customer_name": customer,
        "customer": customer,
        "invoice_name": doc.name,
        "posting_date": getdate(doc.posting_date).strftime("%d-%m-%Y"),
        "due_date": getdate(doc.due_date).strftime("%d-%m-%Y") if doc.due_date else "",
        "total": fmt_money(doc.grand_total, currency=doc.currency),
        "outstanding": fmt_money(doc.outstanding_amount, currency=doc.currency),
        "company": doc.company,
        "items": [
            {"item_name": item.item_name, "qty": item.qty, "amount": fmt_money(item.amount, currency=doc.currency)}
            for item in doc.items
        ],
    }

    template_name = config.get("invoice_template")
    message = _render_template(template_name, context) if template_name else (
        f"Dear {customer}, your invoice {doc.name} for {fmt_money(doc.grand_total, currency=doc.currency)} "
        f"is due on {getdate(doc.due_date).strftime('%d-%m-%Y') if doc.due_date else 'N/A'}. "
        f"Outstanding: {fmt_money(doc.outstanding_amount, currency=doc.currency)}."
    )

    if not message:
        return

    _enqueue_sms(
        phone=phone,
        message=message,
        recipient_name=customer,
        doctype="Sales Invoice",
        docname=doc.name,
        priority=1,
        template=template_name,
    )


def on_payment_submit(doc, method):
    """Payment Entry on_submit hook – sends payment receipt SMS."""
    config = _get_gateway_config()
    if not config.get("send_payment_sms"):
        return

    if doc.doctype != "Payment Entry":
        return

    party = doc.party
    party_type = doc.party_type
    if not party:
        return

    phone = ""
    if party_type == "Customer":
        phone = _get_customer_phone(party)
    elif party_type == "Supplier":
        phone = _get_supplier_phone(party)
    else:
        phone = _clean_phone_from_party(party, party_type)

    if not phone:
        return

    if _check_opt_out(phone):
        return

    context = {
        "party_name": party,
        "party_type": party_type,
        "payment_name": doc.name,
        "amount": fmt_money(doc.paid_amount, currency=doc.currency),
        "posting_date": getdate(doc.posting_date).strftime("%d-%m-%Y"),
        "payment_method": doc.mode_of_payment or "",
        "reference": doc.reference_name or "",
        "company": doc.company,
    }

    template_name = config.get("payment_template")
    message = _render_template(template_name, context) if template_name else (
        f"Dear {party}, payment of {fmt_money(doc.paid_amount, currency=doc.currency)} "
        f"has been received on {getdate(doc.posting_date).strftime('%d-%m-%Y')}. "
        f"Ref: {doc.name}."
    )

    if not message:
        return

    _enqueue_sms(
        phone=phone,
        message=message,
        recipient_name=party,
        doctype="Payment Entry",
        docname=doc.name,
        priority=2,
        template=template_name,
    )


def on_payment_request_submit(doc, method):
    """Payment Request on_submit hook – sends payment link SMS."""
    config = _get_gateway_config()
    if not config.get("send_payment_request_sms"):
        return

    if doc.doctype != "Payment Request":
        return

    party = doc.party
    if not party:
        return

    phone = ""
    if doc.party_type == "Customer":
        phone = _get_customer_phone(party)
    elif doc.party_type == "Supplier":
        phone = _get_supplier_phone(party)

    if not phone:
        return

    if _check_opt_out(phone):
        return

    grand_total = 0
    if doc.reference_doctype and doc.reference_docname:
        try:
            ref_doc = frappe.get_doc(doc.reference_doctype, doc.reference_docname)
            grand_total = getattr(ref_doc, "grand_total", 0)
        except Exception:
            pass

    context = {
        "party_name": party,
        "request_name": doc.name,
        "amount": fmt_money(doc.grand_total, currency=doc.currency),
        "grand_total": fmt_money(grand_total, currency=doc.currency),
        "posting_date": getdate(doc.creation).strftime("%d-%m-%Y"),
        "payment_url": doc.get("payment_url") or doc.get_redirect_url() or "",
        "company": doc.company,
    }

    template_name = config.get("payment_request_template")
    message = _render_template(template_name, context) if template_name else (
        f"Dear {party}, a payment of {fmt_money(doc.grand_total, currency=doc.currency)} "
        f"is requested. Please complete payment using: {doc.get_redirect_url() or 'N/A'}"
    )

    if not message:
        return

    _enqueue_sms(
        phone=phone,
        message=message,
        recipient_name=party,
        doctype="Payment Request",
        docname=doc.name,
        priority=1,
        template=template_name,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_supplier_phone(supplier_name):
    """Look up primary phone for a Supplier via Contact chain."""
    if not supplier_name:
        return ""

    from sms_relay.sms_engine import _clean_phone

    contacts = frappe.db.sql(
        """SELECT c.phone, c.mobile_no
           FROM `tabContact` c
           INNER JOIN `tabDynamic Link` dl
             ON dl.parent = c.name
             AND dl.link_doctype = 'Supplier'
             AND dl.link_name = %s
           WHERE c.phone IS NOT NULL OR c.mobile_no IS NOT NULL
           ORDER BY c.is_primary_contact DESC
           LIMIT 1""",
        (supplier_name,),
        as_dict=True,
    )

    if contacts:
        phone = contacts[0].get("mobile_no") or contacts[0].get("phone") or ""
        return _clean_phone(phone)

    try:
        supplier = frappe.get_doc("Supplier", supplier_name)
        phone = getattr(supplier, "mobile_no", None) or getattr(supplier, "phone", None) or ""
        return _clean_phone(phone)
    except Exception:
        return ""


def _clean_phone_from_party(party, party_type):
    """Generic phone lookup for any party type that has a phone field."""
    from sms_relay.sms_engine import _clean_phone

    try:
        doc = frappe.get_doc(party_type, party)
        phone = getattr(doc, "mobile_no", None) or getattr(doc, "phone", None) or ""
        return _clean_phone(phone)
    except Exception:
        return ""
