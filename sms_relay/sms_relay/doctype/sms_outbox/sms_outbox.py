import frappe
from frappe.model.document import Document

class SMSOutbox(Document):
    def validate(self):
        if self.attempts >= self.max_attempts and self.status != "Failed":
            self.status = "Failed"
