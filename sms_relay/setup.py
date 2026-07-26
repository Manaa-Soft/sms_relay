import frappe

def after_install():
    _create_default_gateway_settings()
    _create_default_templates()
    _create_workspace()

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
            "template_name": "Payment Reminder",
            "message_template": "Dear {{ doc.customer }}, your invoice {{ doc.name }} for {{ frappe.utils.fmt_money(doc.outstanding_amount) }} is overdue. Please pay at your earliest convenience.",
        },
        {
            "template_name": "Order Confirmation",
            "message_template": "Thank you for your order {{ doc.name }}. Total: {{ frappe.utils.fmt_money(doc.grand_total) }}. We will process your order shortly.",
        },
        {
            "template_name": "Dispatch Notification",
            "message_template": "Your order {{ doc.name }} has been dispatched. Expected delivery: {{ doc.delivery_date }}. Tracking will be shared shortly.",
        },
        {
            "template_name": "Payment Link",
            "message_template": "Dear {{ doc.customer }}, pay your invoice {{ doc.name }} ({{ frappe.utils.fmt_money(doc.grand_total) }}) using this link: {{ doc.payment_url }}",
        },
    ]
    for t in templates:
        if not frappe.db.exists("SMS Template", t["template_name"]):
            doc = frappe.new_doc("SMS Template")
            doc.template_name = t["template_name"]
            doc.message_template = t["message_template"]
            doc.insert(ignore_permissions=True)
    frappe.db.commit()

def _create_workspace():
    if frappe.db.exists("Workspace", "SMS Relay"):
        return

    workspace = frappe.get_doc({
        "doctype": "Workspace",
        "name": "SMS Relay",
        "label": "SMS Relay",
        "title": "SMS Relay",
        "module": "SMS Relay",
        "app": "sms_relay",
        "icon": "message-square",
        "type": "Workspace",
        "standard": 1,
        "public": 1,
        "is_hidden": 0,
        "sequence_id": 100,
        "links": [
            {"type": "Card Break", "label": "Messages", "hidden": 0},
            {"type": "Link", "label": "SMS Queue", "link_to": "SMS Queue", "link_type": "DocType", "onboard": 1, "hidden": 0},
            {"type": "Link", "label": "SMS Outbox", "link_to": "SMS Outbox", "link_type": "DocType", "hidden": 0},
            {"type": "Link", "label": "SMS Log", "link_to": "SMS Log", "link_type": "DocType", "hidden": 0},
            {"type": "Link", "label": "SMS Notification Log", "link_to": "SMS Notification Log", "link_type": "DocType", "hidden": 0},
            {"type": "Link", "label": "SMS Opt Out", "link_to": "SMS Opt Out", "link_type": "DocType", "hidden": 0},
            {"type": "Card Break", "label": "Bulk & Campaigns", "hidden": 0},
            {"type": "Link", "label": "SMS Bulk Message", "link_to": "SMS Bulk Message", "link_type": "DocType", "onboard": 1, "hidden": 0},
            {"type": "Link", "label": "SMS Recipient List", "link_to": "SMS Recipient List", "link_type": "DocType", "hidden": 0},
            {"type": "Link", "label": "SMS Template", "link_to": "SMS Template", "link_type": "DocType", "onboard": 1, "hidden": 0},
            {"type": "Card Break", "label": "Settings", "hidden": 0},
            {"type": "Link", "label": "SMS Gateway Settings", "link_to": "SMS Gateway Settings", "link_type": "DocType", "onboard": 1, "hidden": 0},
            {"type": "Link", "label": "SMS Device", "link_to": "SMS Device", "link_type": "DocType", "hidden": 0},
            {"type": "Link", "label": "SMS Notification", "link_to": "SMS Notification", "link_type": "DocType", "hidden": 0},
        ],
        "shortcuts": [
            {"label": "SMS Queue", "link_to": "SMS Queue", "type": "DocType"},
            {"label": "SMS Bulk Message", "link_to": "SMS Bulk Message", "type": "DocType"},
            {"label": "SMS Gateway Settings", "link_to": "SMS Gateway Settings", "type": "DocType"},
        ],
        "content": '[{"id":"h1","type":"header","data":{"text":"<span class=\\"h4\\"><b>SMS Relay</b></span>","col":12}},{"id":"c1","type":"card","data":{"card_name":"Messages","col":4}},{"id":"c2","type":"card","data":{"card_name":"Bulk & Campaigns","col":4}},{"id":"c3","type":"card","data":{"card_name":"Settings","col":4}}]',
    })
    workspace.insert(ignore_permissions=True)
    frappe.db.commit()

def before_tests():
    pass
