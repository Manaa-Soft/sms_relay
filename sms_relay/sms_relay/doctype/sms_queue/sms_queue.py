"""SMS Queue DocType controller.

This module defines the controller for the SMS Queue DocType, an asynchronous
outgoing message queue that decouples SMS creation from delivery.

DocType Fields:
    phone (str): Recipient phone number.
    message (text): Full text content of the SMS to send.
    status (select): Processing status – one of ``Queued``, ``Sending``,
        ``Sent``, ``Delivered``, or ``Failed``.
    priority (int): Send-order priority; lower values are processed first.
    max_retries (int): Maximum number of delivery attempts before marking the
        message as ``Failed``. Auto-populated from global settings when omitted.
    retry_count (int): Number of delivery attempts made so far.
    device (Link → SMS Device): Device assigned for sending (set by the
        scheduler during processing).
    error (text): Last error message if the send attempt failed.

Role in System:
    Other DocTypes insert records into SMS Queue whenever an SMS needs to be
    sent. The ``process_sms_queue`` scheduler job picks up ``Queued`` items
    in priority order, attempts delivery via an available device, and updates
    the status accordingly. Retries are respected up to ``max_retries``.

Status Flow:
    Queued → Sending → Sent/Delivered/Failed
"""

import frappe
from frappe.model.document import Document


class SMSQueue(Document):
    """Controller for the SMS Queue DocType.

    Manages lifecycle hooks for the asynchronous SMS outgoing queue.
    Automatically populates ``max_retries`` from the global SMS Gateway
    Settings when a new record is created without an explicit value.

    Attributes:
        Inherits all fields from the SMS Queue DocType.
    """

    def before_insert(self):
        """Populate ``max_retries`` from global settings before the record is
        persisted for the first time.

        If ``max_retries`` is not already set on the document, this method
        reads the ``max_retry_count`` value from the SMS Gateway Settings
        singleton and applies it, falling back to a default of ``3``.

        Sets:
            self.max_retries (int): The resolved retry limit.
        """
        if not self.max_retries:
            settings = frappe.get_single("SMS Gateway Settings")
            self.max_retries = settings.max_retry_count or 3
