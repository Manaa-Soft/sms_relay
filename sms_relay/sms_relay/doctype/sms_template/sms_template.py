"""SMS Template DocType controller.

This module defines the controller for the SMS Template DocType, which stores
Jinja2 message templates used to generate SMS content for various notification
events.

DocType Fields:
    template_name (str): Unique human-readable name for the template.
    event (str): The system event that triggers this template (e.g. payment
        received, order shipped).
    enabled (bool): Whether this template is active and eligible for use.
    message_template (text): Jinja2 template string. Variables from the
        triggering document's context are available for interpolation.

Role in System:
    When an SMS is triggered by a document event, the system looks up the
    matching enabled template, renders it with Jinja2 using the document's
    data as context, and inserts the resulting text into the SMS Queue.
    Templates allow non-technical users to maintain message wording without
    touching code.

Note:
    A standard SMS supports up to 160 characters in a single segment, but
    modern handsets concatenate longer messages. The 1600-character hard limit
    provides headroom while preventing accidental abuse.
"""

import frappe
from frappe.model.document import Document


class SMSTemplate(Document):
    """Controller for the SMS Template DocType.

    Validates that Jinja2 message templates meet minimum and maximum length
    requirements before they are saved.

    Attributes:
        Inherits all fields from the SMS Template DocType.
    """

    def validate(self):
        """Validate message template length constraints.

        Enforces the following rules:
            1. ``message_template`` must be at least 5 characters (after
               stripping leading/trailing whitespace) to be meaningful.
            2. ``message_template`` must not exceed 1600 characters to remain
               within reasonable SMS concatenation limits.

        Raises:
            frappe.exceptions.ValidationError: If the template is shorter than
                5 characters or longer than 1600 characters.
        """
        if self.message_template and len(self.message_template.strip()) < 5:
            frappe.throw("Message template is too short (minimum 5 characters)")
        if self.message_template and len(self.message_template) > 1600:
            frappe.throw("Message template exceeds 1600 characters (SMS limit)")
