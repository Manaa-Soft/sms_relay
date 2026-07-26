import frappe
from frappe.model.document import Document
from frappe.utils import now

class SMSBulkMessage(Document):
    def validate(self):
        if self.message_type == "Text" and not self.message:
            frappe.throw("Message is required when using Text type")
        if self.message_type == "Template" and not self.template:
            frappe.throw("Template is required when using Template type")

    def before_insert(self):
        self.status = "Draft"
        self.total_recipients = len(self.recipients) if self.recipients else 0
        self.pending_count = self.total_recipients
        self.sent_count = 0
        self.failed_count = 0

    def on_cancel(self):
        self.status = "Cancelled"
