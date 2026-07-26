frappe.provide("sms_relay");

frappe.ui.form.on("SMS Notification", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button("Test Notification", () => {
                _show_test_dialog(frm);
            }, "Tools").addClass("btn-primary-dark");

            frm.add_custom_button("Preview", () => {
                _show_preview_dialog(frm);
            }, "Tools");
        }

        if (frm.doc.reference_doctype) {
            _load_phone_fields(frm, frm.doc.reference_doctype);
        }
    },

    reference_doctype(frm) {
        if (frm.doc.reference_doctype) {
            _load_phone_fields(frm, frm.doc.reference_doctype);
        }
    },

    event(frm) {
        _update_event_description(frm);
    },

    message_template(frm) {
        if (frm.doc.message_template) {
            _update_template_info(frm, frm.doc.message_template);
        }
    }
});

function _load_phone_fields(frm, doctype) {
    frappe.call({
        method: "frappe.client.get",
        args: { doctype: "DocType", name: doctype },
        callback: function(r) {
            if (r.message && r.message.fields) {
                const phone_fields = r.message.fields.filter(f =>
                    f.fieldtype === "Data" && (
                        f.fieldname.includes("phone") ||
                        f.fieldname.includes("mobile") ||
                        f.fieldname.includes("fax") ||
                        (f.options && f.options === "Phone")
                    )
                );
                const fieldnames = phone_fields.map(f => f.fieldname).join("\n");
                frm.set_df_property("phone_field", "description",
                    `Available phone fields: ${fieldnames || "None detected"}`
                );
            }
        }
    });
}

function _update_event_description(frm) {
    const descriptions = {
        "On Submit": "Triggers once when the document is submitted (docstatus becomes 1).",
        "On Save": "Triggers every time the document is saved.",
        "On Validate": "Triggers during validation, before save."
    };
    frm.set_df_property("event", "description", descriptions[frm.doc.event] || "");
}

function _update_template_info(frm, text) {
    const is_gsm7 = /^[\@\£\$\¥\è\é\ù\ì\ò\ç\n\Ø\ø\r\Å\å\Δ\_\Φ\Γ\Λ\Ω\Π\Ψ\Σ\Θ\Ξ\x1bÆæßÉ\s!\"#¤%&'\(\)\*\+,\-\.\/0-9:;<=>?¡A-ZÄÖÑÜ¿a-zäöñüà]+$/.test(text);
    const len = text.length;
    let max_chars, parts;
    if (is_gsm7) {
        max_chars = 160;
        parts = len <= 160 ? 1 : Math.ceil(len / 153);
    } else {
        max_chars = 70;
        parts = len <= 70 ? 1 : Math.ceil(len / 67);
    }
    frm.set_df_property("message_template", "description",
        `Characters: ${len} | Encoding: ${is_gsm7 ? "GSM-7" : "Unicode"} | SMS Parts: ${parts}`
    );
}

function _show_test_dialog(frm) {
    const d = new frappe.ui.Dialog({
        title: "Test SMS Notification",
        fields: [
            {
                label: "Document Type",
                fieldname: "doc_type",
                fieldtype: "Link",
                options: "DocType",
                reqd: 1,
                default: frm.doc.reference_doctype
            },
            {
                label: "Document Name",
                fieldname: "doc_name",
                fieldtype: "Data",
                reqd: 1,
                description: "Enter an existing document name to test with"
            },
            {
                label: "Preview Output",
                fieldname: "preview",
                fieldtype: "Code",
                read_only: 1,
                options: "Text"
            }
        ],
        primary_action_label: "Send Test SMS",
        primary_action: function(values) {
            if (!values.doc_name) {
                frappe.msgprint("Please enter a document name");
                return;
            }
            frappe.call({
                method: "sms_relay.api.endpoints.get_notification_preview",
                args: {
                    notification_name: frm.doc.name,
                    doc_type: values.doc_type,
                    doc_name: values.doc_name
                },
                callback: function(r) {
                    if (r.message) {
                        d.set_value("preview", r.message.message || "No output");
                    }
                }
            });
        }
    });
    d.show();
}

function _show_preview_dialog(frm) {
    const d = new frappe.ui.Dialog({
        title: "Preview Notification",
        fields: [
            {
                label: "Document Type",
                fieldname: "doc_type",
                fieldtype: "Link",
                options: "DocType",
                reqd: 1,
                default: frm.doc.reference_doctype
            },
            {
                label: "Document Name",
                fieldname: "doc_name",
                fieldtype: "Data",
                reqd: 1
            },
            {
                label: "Preview Output",
                fieldname: "preview",
                fieldtype: "Code",
                read_only: 1,
                options: "Text"
            }
        ],
        primary_action_label: "Preview",
        primary_action: function(values) {
            if (!values.doc_name) {
                frappe.msgprint("Please enter a document name");
                return;
            }
            frappe.call({
                method: "sms_relay.api.endpoints.get_notification_preview",
                args: {
                    notification_name: frm.doc.name,
                    doc_type: values.doc_type,
                    doc_name: values.doc_name
                },
                callback: function(r) {
                    if (r.message) {
                        d.set_value("preview", r.message.message || "No output");
                    }
                }
            });
        }
    });
    d.show();
}
