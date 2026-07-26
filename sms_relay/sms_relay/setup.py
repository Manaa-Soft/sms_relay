import frappe

def after_install():
    _create_default_gateway_settings()
    _create_default_templates()

def _create_default_gateway_settings():
    if not frappe.db.exists("SMS Gateway Settings", "SMS Gateway Settings"):
        settings = frappe.new_doc("SMS Gateway Settings")
        settings.sender_name = "RELAY"
        settings.routing_strategy = "Round Robin"
        settings.failover_enabled = 1
        settings.global_rate_limit = 60
        settings.insert(ignore_permissions=True)
        frappe.db.commit()

def _create_default_templates():
    templates = [
        {
            "name": "Payment Reminder",
            "template": "Dear {{ doc.customer }}, your invoice {{ doc.name }} for {{ frappe.utils.fmt_money(doc.outstanding_amount) }} is overdue. Please pay at your earliest convenience. - {{ frappe.defaults.get_global_default('company_name') }}",
        },
        {
            "name": "Order Confirmation",
            "template": "Thank you for your order {{ doc.name }}. Total: {{ frappe.utils.fmt_money(doc.grand_total) }}. We will process your order shortly. - {{ frappe.defaults.get_global_default('company_name') }}",
        },
        {
            "name": "Dispatch Notification",
            "template": "Your order {{ doc.name }} has been dispatched. Expected delivery: {{ doc.delivery_date }}. Tracking will be shared shortly. - {{ frappe.defaults.get_global_default('company_name') }}",
        },
        {
            "name": "Payment Link",
            "template": "Dear {{ doc.customer }}, pay your invoice {{ doc.name }} ({{ frappe.utils.fmt_money(doc.grand_total) }}) using this link: {{ doc.payment_url }} - {{ frappe.defaults.get_global_default('company_name') }}",
        },
    ]
    for t in templates:
        if not frappe.db.exists("SMS Template", t["name"]):
            doc = frappe.new_doc("SMS Template")
            doc.name = t["name"]
            doc.template = t["template"]
            doc.insert(ignore_permissions=True)
    frappe.db.commit()

def before_tests():
    pass
