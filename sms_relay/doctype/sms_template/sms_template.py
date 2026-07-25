import frappe
from frappe.model.document import Document


class SMSTemplate(Document):
    def validate(self):
        if self.message_template and len(self.message_template.strip()) < 5:
            frappe.throw("Message template is too short (minimum 5 characters)")
        if self.message_template and len(self.message_template) > 1600:
            frappe.throw("Message template exceeds 1600 characters (SMS limit)")
