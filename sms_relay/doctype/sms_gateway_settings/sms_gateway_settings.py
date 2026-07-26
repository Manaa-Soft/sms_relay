"""SMS Gateway Settings DocType controller.

This module defines the controller for the SMS Gateway Settings DocType,
a singleton document that holds all global SMS relay configuration for the
sms_relay application.

DocType Fields:
    gateway_url (str): Base URL of the SMS gateway HTTP API endpoint.
    api_key (str): Authentication key for the gateway API.
    gateway_enabled (bool): Master toggle to enable/disable the entire SMS relay.
    notification_enabled (bool): Toggle for sending SMS notifications on events.
    rate_limit_per_minute (int): Maximum SMS messages allowed per minute (0–60).
    webhook_enabled (bool): Whether the inbound webhook endpoint is active.
    webhook_token (str): Shared secret for validating inbound webhook requests.
    max_retry_count (int): Default number of retry attempts for failed SMS sends.
    compliance_text (str): Opt-out / compliance footer appended to messages.

Role in System:
    Acts as the central configuration hub. Scheduler jobs, queue processors,
    and other DocType controllers read from this singleton to determine
    connection parameters, rate limits, retry policies, and feature toggles.
"""

import frappe
from frappe.model.document import Document


class SMSGatewaySettings(Document):
    """Controller for the SMS Gateway Settings singleton DocType.

    Manages global SMS relay configuration including gateway connection details,
    notification toggles, rate limiting, webhook settings, and compliance options.
    Only one instance of this document exists in the system at any time.

    Attributes:
        Inherits all fields from the SMS Gateway Settings DocType.
    """

    def validate(self):
        """Validate and normalise gateway settings before saving.

        Performs the following checks:
            1. Strips any trailing ``/`` from ``gateway_url`` to ensure
               consistent URL concatenation downstream.
            2. Ensures ``rate_limit_per_minute`` does not exceed 60 (one per
               second), throwing an error if it does.

        Raises:
            frappe.exceptions.ValidationError: If ``rate_limit_per_minute``
                is greater than 60.
        """
        if self.gateway_url:
            self.gateway_url = self.gateway_url.rstrip("/")
        if self.rate_limit_per_minute and self.rate_limit_per_minute > 60:
            frappe.throw("Rate limit cannot exceed 60 per minute")
