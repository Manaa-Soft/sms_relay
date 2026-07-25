import frappe
from frappe.model.document import Document


class SMSGatewaySettings(Document):
    def validate(self):
        if self.gateway_url:
            self.gateway_url = self.gateway_url.rstrip("/")
        if self.rate_limit_per_minute and self.rate_limit_per_minute > 60:
            frappe.throw("Rate limit cannot exceed 60 per minute")
