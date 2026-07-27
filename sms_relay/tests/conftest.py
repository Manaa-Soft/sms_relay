import frappe
from frappe.tests import IntegrationTestCase


class SMSRelayTestCase(IntegrationTestCase):
    """Base test case for sms_relay tests.

    Creates required fixtures: Gateway Settings, Device, Template.
    Cleans up after each test.
    """

    def setUp(self):
        self._setup_gateway_settings()
        self._setup_device()
        self._setup_template()

    def tearDown(self):
        frappe.db.rollback()

    def _setup_gateway_settings(self):
        settings = frappe.get_single("SMS Gateway Settings")
        settings.enabled = 1
        settings.gateway_url = "http://localhost:8085"
        settings.api_path = "/api/3rdparty/v1/message"
        settings.timeout = 5
        settings.routing_strategy = "Round Robin"
        settings.failover_enabled = 1
        settings.global_rate_limit = 60
        settings.check_opt_out = 1
        settings.send_interval_min = 0
        settings.send_interval_max = 0
        settings.save(ignore_permissions=True)

    def _setup_device(self):
        if not frappe.db.exists("SMS Device", "Test Phone"):
            device = frappe.new_doc("SMS Device")
            device.device_name = "Test Phone"
            device.server_url = "http://localhost:8085"
            device.username = "test_user"
            device.password = "test_pass"
            device.sim_number = 1
            device.priority = 0
            device.is_active = 1
            device.daily_quota = 200
            device.hourly_quota = 500
            device.gateway_type = "Android SMS Gateway"
            device.insert(ignore_permissions=True)
        else:
            frappe.db.set_value("SMS Device", "Test Phone", {
                "is_active": 1,
                "is_online": 1,
                "daily_quota": 200,
                "hourly_quota": 500,
            })

    def _setup_template(self):
        if not frappe.db.exists("SMS Template", {"template_name": "Test Template"}):
            tmpl = frappe.new_doc("SMS Template")
            tmpl.template_name = "Test Template"
            tmpl.category = "UTILITY"
            tmpl.language = "en"
            tmpl.message_template = "Hello {{ doc.customer }}, your total is {{ doc.grand_total }}."
            tmpl.insert(ignore_permissions=True)
        if not frappe.db.exists("SMS Template", {"template_name": "Empty Template"}):
            tmpl = frappe.new_doc("SMS Template")
            tmpl.template_name = "Empty Template"
            tmpl.category = "UTILITY"
            tmpl.language = "en"
            tmpl.message_template = ""
            tmpl.insert(ignore_permissions=True)
        if not frappe.db.exists("SMS Template", {"template_name": "Param Template"}):
            tmpl = frappe.new_doc("SMS Template")
            tmpl.template_name = "Param Template"
            tmpl.category = "UTILITY"
            tmpl.language = "en"
            tmpl.message_template = "Hello {{1}}, order {{2}} ready."
            tmpl.insert(ignore_permissions=True)
