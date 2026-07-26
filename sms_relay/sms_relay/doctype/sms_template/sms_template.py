import frappe
from frappe.model.document import Document


class SMSTemplate(Document):
    def validate(self):
        if self.message_template and len(self.message_template.strip()) < 5:
            frappe.throw("Message template is too short (minimum 5 characters)")
        if self.message_template and len(self.message_template) > 1600:
            frappe.throw("Message template exceeds 1600 characters (SMS limit)")
        self.char_count = len(self.message_template) if self.message_template else 0
        if self.char_count <= 160:
            self.sms_parts = 1 if self.char_count > 0 else 0
        else:
            self.sms_parts = -(-self.char_count // 153)
        if not self.actual_name:
            self.actual_name = self.template_name
