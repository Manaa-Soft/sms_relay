"""SMS Log DocType controller.

This module defines the controller for the SMS Log DocType, which serves as a
read-only audit trail for every SMS message processed by the relay system.

DocType Fields:
    phone (str): Recipient phone number.
    message (text): Full text content of the SMS message.
    status (select): Current delivery status – one of ``Sent``, ``Delivered``,
        or ``Failed``.
    device (Link → SMS Device): The device that was used to send the message.
    reference_doctype (str): DocType name of the document that triggered this
        SMS (e.g. ``Sales Invoice``, ``Notification``).
    reference_name (str): Name (primary key) of the triggering document.
    message_id (str): Unique identifier returned by the gateway for tracking.
    error (text): Error details when the message status is ``Failed``.
    sent_on (datetime): Timestamp when the message was dispatched.
    delivered_on (datetime): Timestamp when delivery confirmation was received.

Role in System:
    Provides a complete, immutable log of all outbound SMS traffic for
    debugging, auditing, and reporting purposes. Records are inserted by the
    queue processor after each send attempt and are never modified afterward.

Note:
    No custom controller logic is required; the class inherits from Document
    directly and relies on default Frappe behaviour.
"""

import frappe
from frappe.model.document import Document


class SMSLog(Document):
    """Controller for the SMS Log DocType.

    Acts as a read-only audit record for all SMS messages dispatched through
    the relay. No custom validation or lifecycle hooks are needed; instances
    are created programmatically by the queue processor.
    """

    pass
