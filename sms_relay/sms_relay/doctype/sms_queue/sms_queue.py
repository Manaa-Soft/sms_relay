import frappe
from frappe.model.document import Document


class SMSQueue(Document):
    def before_insert(self):
        if not self.max_retries:
            settings = frappe.get_single("SMS Gateway Settings")
            self.max_retries = settings.max_retry_count or 3
