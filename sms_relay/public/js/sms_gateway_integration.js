// SMS Gateway Integration for Frappe/ERPNext
// Loaded via hooks.py app_include_js

frappe.provide("sms_relay");

frappe.ready(function () {
    frappe.provide("sms_relay");

    // Add SMS status indicator to Sales Invoice
    if (frappe.boot.sysdefaults.country === "Saudi Arabia" ||
        frappe.boot.sysdefaults.country === "Yemen") {
        frappe.router.add_setup_gem("sms_relay");
    }
});

// SMS Status in form view
frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && !frm.is_new()) {
            frm.add_custom_button(__("Send SMS"), function () {
                const d = new frappe.ui.Dialog({
                    title: __("Send SMS"),
                    fields: [
                        {
                            label: __("Phone Number"),
                            fieldname: "phone",
                            fieldtype: "Data",
                            reqd: 1,
                            default: frm.doc.contact_mobile || frm.doc.mobile_no || "",
                        },
                        {
                            label: __("Message"),
                            fieldname: "message",
                            fieldtype: "Small Text",
                            reqd: 1,
                            default: `Dear ${frm.doc.customer_name}, your invoice ${frm.doc.name} for ${frappe.format(frm.doc.grand_total, { fieldtype: "Currency", options: frm.doc.currency })} is ready. Please check your email for details.`,
                        },
                    ],
                    primary_action_label: __("Send"),
                    primary_action(values) {
                        frappe.call({
                            method: "sms_relay.api.send_sms_now",
                            args: {
                                recipient: values.phone,
                                message: values.message,
                                doctype: "Sales Invoice",
                                docname: frm.doc.name,
                            },
                            callback(r) {
                                if (r.message && r.message.success) {
                                    frappe.show_alert({
                                        message: __("SMS sent successfully"),
                                        indicator: "green",
                                    });
                                } else {
                                    frappe.show_alert({
                                        message: __("SMS failed: ") + (r.message?.error || "Unknown error"),
                                        indicator: "red",
                                    });
                                }
                            },
                        });
                        d.hide();
                    },
                });
                d.show();
            }, __("Communication"));
        }
    },
});

// Payment Entry SMS notification
frappe.ui.form.on("Payment Entry", {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && !frm.is_new()) {
            frm.add_custom_button(__("Send SMS"), function () {
                const phone = frm.doc.party_mobile || "";
                const msg = `Dear ${frm.doc.party_name || ""}, we have received payment of ${frappe.format(frm.doc.paid_amount, { fieldtype: "Currency", options: frm.doc.paid_from_account_currency })} for ${frm.doc.reference_name || "your account"}. Thank you!`;

                frappe.call({
                    method: "sms_relay.api.send_sms_now",
                    args: {
                        recipient: phone,
                        message: msg,
                        doctype: "Payment Entry",
                        docname: frm.doc.name,
                    },
                    callback(r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({ message: __("SMS sent!"), indicator: "green" });
                        } else {
                            frappe.show_alert({ message: __("SMS failed"), indicator: "red" });
                        }
                    },
                });
            }, __("Communication"));
        }
    },
});

// SMS Gateway Health Dashboard
frappe.pages["sms-gateway-dashboard"] = function () {
    const page = frappe.get_doc({ doctype: "SMS Gateway Settings" });

    frappe.require("sms_relay.sms_gateway_integration.css");

    const wrapper = page.main;
    wrapper.innerHTML = `
        <div class="sms-dashboard">
            <div class="row" id="sms-status-cards"></div>
            <div class="row mt-3">
                <div class="col-md-8">
                    <div class="card" id="sms-recent-logs">
                        <div class="card-header">${__("Recent SMS Activity")}</div>
                        <div class="card-body" id="recent-sms-list"></div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card" id="sms-device-status">
                        <div class="card-header">${__("Device Status")}</div>
                        <div class="card-body" id="device-status-list"></div>
                    </div>
                </div>
            </div>
        </div>
    `;

    load_dashboard_data();
};

function load_dashboard_data() {
    frappe.call({
        method: "sms_relay.api.get_sms_stats",
        callback(r) {
            if (r.message) {
                const stats = r.message;
                document.getElementById("sms-status-cards").innerHTML = `
                    <div class="col-md-3">
                        <div class="card text-center">
                            <div class="card-body">
                                <h5 class="text-success">${stats.sent_today || 0}</h5>
                                <p class="text-muted">${__("Sent Today")}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card text-center">
                            <div class="card-body">
                                <h5 class="text-danger">${stats.failed_today || 0}</h5>
                                <p class="text-muted">${__("Failed Today")}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card text-center">
                            <div class="card-body">
                                <h5 class="text-warning">${stats.pending || 0}</h5>
                                <p class="text-muted">${__("Pending")}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card text-center">
                            <div class="card-body">
                                <h5 class="text-info">${stats.delivered || 0}</h5>
                                <p class="text-muted">${__("Delivered")}</p>
                            </div>
                        </div>
                    </div>
                `;
            }
        },
    });
}
