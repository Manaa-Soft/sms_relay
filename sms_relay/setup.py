import frappe

def after_install():
    _create_default_gateway_settings()
    _create_default_templates()

def _create_default_gateway_settings():
    if not frappe.db.exists("SMS Gateway Settings", "SMS Gateway Settings"):
        settings = frappe.new_doc("SMS Gateway Settings")
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

def after_migrate():
    """Run after every `bench migrate` — keeps the app visible on the desk.

    Frappe v16+ has two desk home modes (`Desktop Settings -> Desktop Page`):

    - **Apps** (default on fresh installs, hook-driven): sms_relay appears because it
      declares the `add_to_apps_screen` hook, so nothing is needed here.
    - **Desktop Icons** (older/upgraded sites are switched here by the frappe v16 patch
      `keep_existing_sites_on_desktop_icons`): the grid is drawn from the `Desktop Icon`
      doctype, and icons are only seeded while an app is *installed* in that mode. sms_relay
      ships no `desktop_icons/` fixture, so on upgraded sites it dropped off the desk.

    Seeding the icon here (idempotent, a no-op in Apps mode) keeps the app visible whichever
    mode the site uses. Falls back silently on Frappe versions without the seeding API.
    """
    _ensure_sms_relay_desktop_icon()


def _ensure_sms_relay_desktop_icon():
    try:
        from frappe.utils.install import create_desktop_icons_for_app
    except ImportError:
        return
    try:
        create_desktop_icons_for_app("sms_relay")
    except Exception as e:
        frappe.log_error(f"Failed to seed SMS Relay desktop icon: {e}", "sms_relay.setup.after_migrate")

def before_tests():
    pass
