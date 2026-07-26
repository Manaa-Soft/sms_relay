import frappe
from frappe.model.document import Document

class SMSRecipientList(Document):
    def validate(self):
        if not self.recipients:
            frappe.throw("At least one recipient is required")
