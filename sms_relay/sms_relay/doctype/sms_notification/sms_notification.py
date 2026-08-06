"""SMS Notification — mirrors WhatsApp Notification pattern."""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.safe_exec import get_safe_globals, safe_exec

from sms_relay.core.sms_utils import clean_phone, is_opted_out


class SMSNotification(Document):
    """SMS Notification."""

    def validate(self):
        if self.notification_type == "DocType Event":
            fields = frappe.get_doc("DocType", self.reference_doctype).fields
            custom_fields = frappe.get_all(
                "Custom Field",
                filters={"dt": self.reference_doctype},
                fields=["fieldname"],
            )
            fields += custom_fields
            if self.field_name and not any(
                f.fieldname == self.field_name for f in fields
            ):
                frappe.throw(
                    _("Field {0} does not exist on {1}").format(
                        self.field_name, self.reference_doctype
                    )
                )

        if self.set_property_after_alert:
            meta = frappe.get_meta(self.reference_doctype)
            if not meta.get_field(self.set_property_after_alert):
                frappe.throw(
                    _("Field {0} not found on DocType {1}").format(
                        self.set_property_after_alert, self.reference_doctype
                    )
                )

    # ─── DocType Event path ──────────────────────────────────────────

    def send_template_message(self, doc, phone_no=None, default_template=None, ignore_condition=False, template=None):
        """Specific to Document Event triggered Server Scripts."""
        if self.disabled:
            return

        doc_data = doc.as_dict()
        effective_template = self._resolve_language_template(template or self.template, doc)

        if self.condition and not ignore_condition:
            if not frappe.safe_eval(
                self.condition, get_safe_globals(), dict(doc=doc_data)
            ):
                return

        if self.field_name:
            phone_number = phone_no or doc_data.get(self.field_name)
        else:
            phone_number = phone_no

        if not phone_number:
            return

        cleaned = clean_phone(str(phone_number))
        if not cleaned:
            return
        if is_opted_out(cleaned):
            return

        message = self._render_message(doc, effective_template)
        if not message:
            return

        self._send_sms(cleaned, message, doc_data, effective_template)

        if doc_data and self.set_property_after_alert:
            prop_name = self.set_property_after_alert
            value = self.property_value
            if doc_data.get("doctype") and doc_data.get("name"):
                meta = frappe.get_meta(doc_data.get("doctype"))
                df = meta.get_field(prop_name)
                if df:
                    if df.fieldtype in frappe.model.numeric_fieldtypes:
                        value = frappe.utils.cint(value)
                    frappe.db.set_value(
                        doc_data.get("doctype"),
                        doc_data.get("name"),
                        prop_name,
                        value,
                    )

        frappe.msgprint(_("SMS triggered"), indicator="green", alert=True)

        frappe.get_doc({
            "doctype": "SMS Notification Log",
            "notification": self.name,
            "reference_doctype": doc_data.get("doctype"),
            "reference_name": doc_data.get("name"),
            "phone": cleaned,
            "message": message,
            "status": "Sent",
        }).insert(ignore_permissions=True)

    # ─── Scheduler Event path ────────────────────────────────────────

    def send_scheduled_message(self):
        """Specific to Scheduler Event triggered."""
        if self.condition:
            safe_exec(
                self.condition, get_safe_globals(), dict(doc=self)
            )

        if self.get("scheduler_data_source") == "Overdue Invoices":
            self._build_overdue_invoice_data()

        if self.get("_contact_list"):
            for contact in self._contact_list:
                cleaned = clean_phone(str(contact))
                if cleaned and not is_opted_out(cleaned):
                    message = self._render_message(None)
                    if message:
                        self._send_sms(cleaned, message, None)

        elif self.get("_data_list"):
            for data in self._data_list:
                doc = frappe.get_doc(self.reference_doctype, data.get("name"))
                phone_no = data.get("phone_no")
                self.send_template_message(
                    doc, phone_no, ignore_condition=True, template=data.get("template")
                )

    def _build_overdue_invoice_data(self):
        """Build ``_data_list`` from overdue Sales Invoices.

        Each item resolves the recipient phone (via the Customer) and the
        template to use (by invoice/Customer language).  Mirrors the legacy
        ``send_overdue_reminders`` query (submitted, outstanding balance past
        due date, limit 50).
        """
        from sms_relay.core.sms_engine import _get_customer_phone
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "outstanding_amount": [">", 0],
                "due_date": ["<", frappe.utils.getdate()],
            },
            fields=["name", "customer"],
            limit=50,
        )
        data = []
        for inv in invoices:
            phone = _get_customer_phone(inv.customer)
            if not phone:
                continue
            data.append({
                "name": inv.name,
                "phone_no": phone,
                "template": self._template_for_invoice(inv.name, inv.customer),
            })
        self.set("_data_list", data)

    def _template_for_invoice(self, invoice_name, customer):
        """Pick the SMS Template per recipient based on language.

        Arabic recipients get the "(Arabic)" variant; everyone else falls back
        to the notification's configured template.
        """
        lang = (
            frappe.db.get_value("Sales Invoice", invoice_name, "language")
            or frappe.db.get_value("Customer", customer, "language")
        )
        if lang:
            code = frappe.db.get_value("Language", lang, "language_code") or ""
            if str(code).lower().startswith("ar"):
                return "{} (Arabic)".format(self.template)
        return self.template

    def _resolve_language_template(self, template_name, doc):
        """Auto-select an "(Arabic)" template variant for Arabic recipients.

        The recipient language is read from the document's ``language`` field
        (or the linked Customer), mirroring the scheduler's Overdue Invoices
        selection so DocType Event notifications are localized the same way.
        Falls back to the configured template when the variant does not exist.
        """
        if not template_name or not doc:
            return template_name
        lang = doc.get("language")
        if not lang and doc.get("customer"):
            lang = frappe.db.get_value("Customer", doc.get("customer"), "language")
        if lang:
            code = frappe.db.get_value("Language", lang, "language_code") or ""
            if str(code).lower().startswith("ar"):
                candidate = "{} (Arabic)".format(template_name)
                if frappe.db.exists("SMS Template", candidate):
                    return candidate
        return template_name

    # ─── Shared helpers ──────────────────────────────────────────────

    def _render_message(self, doc, template=None):
        """Render message based on template_type.

        Jinja:     {{ doc.field_name }} rendered via Jinja2
        Parameter: {{1}}, {{2}} replaced from the ``fields`` child table (no Jinja)
        """
        template_name = template or self.template
        if template_name:
            try:
                template_doc = frappe.get_doc("SMS Template", template_name)
                body = template_doc.message_template or ""
                if not body:
                    return ""
                if self.template_type == "Parameter":
                    return self._replace_positional_params(body, doc).strip()
                body = self._replace_positional_params(body, doc)
                from jinja2 import Template
                tmpl = Template(body)
                context = {"doc": doc, "frappe": frappe} if doc else {"doc": None, "frappe": frappe}
                return tmpl.render(**context).strip()
            except Exception:
                return ""

        message_template = self.message_template
        if not message_template:
            return ""
        if self.template_type == "Parameter":
            return self._replace_positional_params(message_template, doc).strip()
        message_template = self._replace_positional_params(message_template, doc)
        from jinja2 import Template
        tmpl = Template(message_template)
        context = {"doc": doc, "frappe": frappe} if doc else {"doc": None, "frappe": frappe}
        try:
            return tmpl.render(**context).strip()
        except Exception:
            return ""

    def _replace_positional_params(self, text, doc):
        """Replace {{1}}, {{2}}, ... with values from the ``fields`` child table.

        Each row in ``self.fields`` maps a positional parameter to a DocType
        field name.  ``{{1}}`` is replaced with the value of the first row's
        field, ``{{2}}`` with the second, and so on.
        """
        if not self.fields or not doc:
            return text
        import re
        params = []
        for row in self.fields:
            field_name = row.field_name
            if hasattr(doc, "get_formatted"):
                value = doc.get_formatted(field_name) or ""
            else:
                value = str(doc.get(field_name)) if doc.get(field_name) else ""
            params.append(str(value))
        def _replace(match):
            idx = int(match.group(1)) - 1
            return params[idx] if 0 <= idx < len(params) else match.group(0)
        return re.sub(r"\{\{(\d+)\}\}", _replace, text)

    def _send_sms(self, phone, message, doc_data=None, template=None):
        """Enqueue SMS for sending."""
        from sms_relay.core.sms_engine import _enqueue_sms
        priority = "High" if any(w in message.lower() for w in ("payment", "otp")) else "Normal"
        extras = {}
        if doc_data and doc_data.get("doctype") and doc_data.get("name"):
            extras["reference_doctype"] = doc_data.get("doctype")
            extras["reference_name"] = doc_data.get("name")
        template = template or self.template
        if template:
            extras["template"] = template
        queue = _enqueue_sms(
            phone=phone,
            message=message,
            priority=priority,
            **extras,
        )
        return queue

    def on_trash(self):
        frappe.cache().delete_value("sms_notification_map")
