import frappe
from frappe.model.document import Document
from frappe.utils import now

class SMSOptOut(Document):
    def validate(self):
        self.phone = self.phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

    def before_insert(self):
        self.opted_out_date = now()

    def on_update(self):
        if self.opted_out:
            frappe.cache().delete_key(f"sms_opted_out:{self.phone}")

    def after_delete(self):
        frappe.cache().delete_key(f"sms_opted_out:{self.phone}")
