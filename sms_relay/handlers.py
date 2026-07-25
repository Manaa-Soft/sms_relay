"""Frappe document event handlers for SMS notifications.

This module contains ``doc_events`` hooks that trigger SMS messages when
specific ERPNext/Frappe documents are submitted.  The three supported
document types are:

* **Sales Invoice** – ``on_invoice_submit``
* **Payment Entry** – ``on_payment_submit``
* **Payment Request** – ``on_payment_request_submit``

Each handler follows a common flow:

1. Fetch the global SMS gateway configuration via ``_get_gateway_config``.
2. Check the relevant feature flag (e.g. ``send_invoice_sms``) – bail out
   early when the feature is disabled.
3. Determine the recipient's phone number by walking the Contact → Dynamic
   Link chain for the associated party (Customer, Supplier, etc.).
4. Verify the phone number is **not** opted-out of SMS notifications.
5. Build a Jinja-renderable context dict from the document fields.
6. Render the configured Jinja template (or fall back to a plain-text
   default message).
7. Enqueue the SMS for delivery via ``_enqueue_sms``.

Helper functions for phone-number lookup live at the bottom of this module
(``_get_supplier_phone`` and ``_clean_phone_from_party``).
"""

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
    """Send an SMS notification when a Sales Invoice is submitted.

    Triggered by the ``doc_events`` hook for **Sales Invoice** ``on_submit``.

    The handler first checks the gateway config flag ``send_invoice_sms``.
    When disabled the function returns immediately without side-effects.

    **Flow:**

    1. Guard: feature flag ``send_invoice_sms`` must be enabled.
    2. Guard: ``doc.doctype`` must be ``"Sales Invoice"``.
    3. Guard: the invoice must have a ``customer``.
    4. Resolve the customer's phone number via ``_get_customer_phone``.
    5. Guard: the phone must not be opted-out (``_check_opt_out``).
    6. Build the template context dict (see *Template Variables* below).
    7. Render the Jinja template named in ``config["invoice_template"]``,
       or fall back to a built-in plain-text string.
    8. Enqueue the SMS at **priority 1**.

    Args:
        doc: The Sales Invoice document instance being submitted.
        method: The Frappe hook method name (``"on_submit"``).  Present for
            API compatibility but not used inside the function.

    Returns:
        None.  Side-effect: an SMS is enqueued when all guards pass.

    Template Variables:
        customer_name (str): Display name of the customer.
        customer (str): ID of the customer record.
        invoice_name (str): Name / ID of the Sales Invoice.
        posting_date (str): Invoice date formatted as ``DD-MM-YYYY``.
        due_date (str): Due date formatted as ``DD-MM-YYYY``, or empty.
        total (str): Grand total formatted with currency symbol.
        outstanding (str): Outstanding amount formatted with currency symbol.
        company (str): Company name from the invoice.
        items (list[dict]): Line items, each containing ``item_name``,
            ``qty``, and ``amount`` (formatted with currency symbol).
    """
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
    """Send an SMS notification when a Payment Entry is submitted.

    Triggered by the ``doc_events`` hook for **Payment Entry** ``on_submit``.

    The handler first checks the gateway config flag ``send_payment_sms``.
    When disabled the function returns immediately without side-effects.

    **Flow:**

    1. Guard: feature flag ``send_payment_sms`` must be enabled.
    2. Guard: ``doc.doctype`` must be ``"Payment Entry"``.
    3. Guard: the payment must have a ``party``.
    4. Resolve the party's phone number based on ``party_type``:

       * ``"Customer"`` → ``_get_customer_phone``
       * ``"Supplier"``  → ``_get_supplier_phone``
       * Anything else  → ``_clean_phone_from_party``

    5. Guard: the phone must not be opted-out (``_check_opt_out``).
    6. Build the template context dict (see *Template Variables* below).
    7. Render the Jinja template named in ``config["payment_template"]``,
       or fall back to a built-in plain-text string.
    8. Enqueue the SMS at **priority 2**.

    Args:
        doc: The Payment Entry document instance being submitted.
        method: The Frappe hook method name (``"on_submit"``).  Present for
            API compatibility but not used inside the function.

    Returns:
        None.  Side-effect: an SMS is enqueued when all guards pass.

    Template Variables:
        party_name (str): ID of the receiving party.
        party_type (str): Frappe DocType of the party (e.g. ``"Customer"``).
        payment_name (str): Name / ID of the Payment Entry.
        amount (str): Paid amount formatted with currency symbol.
        posting_date (str): Payment date formatted as ``DD-MM-YYYY``.
        payment_method (str): Mode of payment, or empty string.
        reference (str): Reference document name, or empty string.
        company (str): Company name from the payment entry.
    """
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
    """Send an SMS with a payment link when a Payment Request is submitted.

    Triggered by the ``doc_events`` hook for **Payment Request**
    ``on_submit``.

    The handler first checks the gateway config flag
    ``send_payment_request_sms``.  When disabled the function returns
    immediately without side-effects.

    **Flow:**

    1. Guard: feature flag ``send_payment_request_sms`` must be enabled.
    2. Guard: ``doc.doctype`` must be ``"Payment Request"``.
    3. Guard: the request must have a ``party``.
    4. Resolve the party's phone number based on ``party_type``:

       * ``"Customer"`` → ``_get_customer_phone``
       * ``"Supplier"``  → ``_get_supplier_phone``

    5. Guard: the phone must not be opted-out (``_check_opt_out``).
    6. Attempt to fetch the ``grand_total`` from the referenced document
       (if ``reference_doctype`` / ``reference_docname`` are set).
    7. Build the template context dict (see *Template Variables* below).
    8. Render the Jinja template named in
       ``config["payment_request_template"]``, or fall back to a built-in
       plain-text string that includes the payment redirect URL.
    9. Enqueue the SMS at **priority 1**.

    Args:
        doc: The Payment Request document instance being submitted.
        method: The Frappe hook method name (``"on_submit"``).  Present for
            API compatibility but not used inside the function.

    Returns:
        None.  Side-effect: an SMS is enqueued when all guards pass.

    Template Variables:
        party_name (str): ID of the receiving party.
        request_name (str): Name / ID of the Payment Request.
        amount (str): Requested grand total formatted with currency symbol.
        grand_total (str): Grand total of the referenced document formatted
            with currency symbol (falls back to ``"0"`` if unavailable).
        posting_date (str): Request creation date formatted as ``DD-MM-YYYY``.
        payment_url (str): Redirect URL for completing the payment.
        company (str): Company name from the payment request.
    """
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
    """Look up the primary phone number for a Supplier via the Contact chain.

    The lookup proceeds in two stages:

    1. **Contact → Dynamic Link join** – queries ``tabContact`` joined with
       ``tabDynamic Link`` to find contacts linked to the given Supplier.
       Results are ordered by ``is_primary_contact DESC`` so the primary
       contact's number is returned first.  ``mobile_no`` is preferred over
       ``phone``.
    2. **Direct Supplier fields** – if no linked contacts are found, the
       function falls back to reading ``mobile_no`` / ``phone`` attributes
       directly from the Supplier document.

    In both cases the raw number is passed through ``_clean_phone`` before
    returning.

    Args:
        supplier_name (str): The name / ID of the Supplier to look up.
            When falsy, the function short-circuits and returns an empty
            string.

    Returns:
        str: A cleaned phone number string, or an empty string when no
        number could be determined.
    """
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
    """Perform a generic phone-number lookup for an arbitrary party type.

    Unlike ``_get_customer_phone`` / ``_get_supplier_phone`` which walk the
    Contact → Dynamic Link chain, this helper fetches the party document
    directly and reads its ``mobile_no`` or ``phone`` attributes.

    This is used as a catch-all when ``party_type`` is neither ``"Customer"``
    nor ``"Supplier"``.

    Args:
        party (str): The name / ID of the party record to look up.
        party_type (str): The Frappe DocType of the party (e.g.
            ``"Employee"``, ``"Student"``, etc.).

    Returns:
        str: A cleaned phone number string, or an empty string when the
        party document cannot be fetched or has no phone fields.
    """
    from sms_relay.sms_engine import _clean_phone

    try:
        doc = frappe.get_doc(party_type, party)
        phone = getattr(doc, "mobile_no", None) or getattr(doc, "phone", None) or ""
        return _clean_phone(phone)
    except Exception:
        return ""
