import frappe
from frappe.model.document import Document


class SMSDevice(Document):
    def validate(self):
        if self.sent_today and self.daily_quota and self.sent_today > self.daily_quota:
            frappe.throw(f"Daily quota ({self.daily_quota}) exceeded for device {self.device_name}")
