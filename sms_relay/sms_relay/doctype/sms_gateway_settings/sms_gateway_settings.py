import frappe
from frappe.model.document import Document


class SMSGatewaySettings(Document):
    def validate(self):
        if self.gateway_url:
            self.gateway_url = self.gateway_url.rstrip("/")
