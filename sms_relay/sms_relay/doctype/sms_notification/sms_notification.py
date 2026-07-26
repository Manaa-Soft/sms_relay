import frappe
from frappe.model.document import Document

class SMSNotification(Document):
    def validate(self):
        if self.set_property_after_alert and not self.property_value:
            frappe.throw("Property Value is required when Set Property After Alert is set")
