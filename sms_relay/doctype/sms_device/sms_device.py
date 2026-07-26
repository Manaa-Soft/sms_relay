"""SMS Device DocType controller.

This module defines the controller for the SMS Device DocType, which represents
a registered Android phone connected to the SMS relay gateway.

DocType Fields:
    device_id (str): Unique hardware or app-level identifier for the device.
    device_name (str): Human-readable label for the device.
    priority (int): Ordering priority used when selecting a device for sending
        (lower values are preferred).
    daily_quota (int): Maximum number of SMS messages the device may send per
        day. Acts as a per-device safety limit.
    sent_today (int): Running counter of messages sent through this device on
        the current day. Reset by the daily scheduler job.
    last_heartbeat (datetime): Timestamp of the most recent ping received from
        the device, used to determine online/offline status.
    enabled (bool): Whether the device is active and eligible for message routing.

Role in System:
    The gateway routes outgoing SMS messages to available devices based on
    priority and current load. Each device tracks its own daily usage to
    prevent exceeding carrier quotas.
"""

import frappe
from frappe.model.document import Document


class SMSDevice(Document):
    """Controller for the SMS Device DocType.

    Represents a single Android phone that participates in the SMS relay
    network. Validates that the device's daily send count does not exceed
    its configured quota.

    Attributes:
        Inherits all fields from the SMS Device DocType.
    """

    def validate(self):
        """Validate device constraints before saving.

        Checks that ``sent_today`` does not exceed ``daily_quota``. If it
        does, the document save is rejected with an informative error message.

        Raises:
            frappe.exceptions.ValidationError: If ``sent_today`` is greater
                than ``daily_quota`` for this device.
        """
        if self.sent_today and self.daily_quota and self.sent_today > self.daily_quota:
            frappe.throw(f"Daily quota ({self.daily_quota}) exceeded for device {self.device_name}")
