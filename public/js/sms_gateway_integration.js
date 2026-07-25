frappe.provide("sms_relay");

frappe.ui.form.on("Sales Invoice", {
    refresh: function (frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__("Send SMS"), function () {
                frappe.call({
                    method: "sms_relay.api.send_sms_now",
                    args: {
                        recipient: frm.doc.customer_phone || "",
                        message: "",
                        template: "",
                    },
                    callback: function (r) {
                        if (r.message && r.message.status === "sent") {
                            frappe.show_alert({
                                message: __("SMS sent successfully via {0}", [r.message.device]),
                                indicator: "green",
                            });
                        }
                    },
                });
            }).addClass("btn-primary");

            frappe.call({
                method: "sms_relay.api.get_sms_stats",
                callback: function (r) {
                    if (r.message) {
                        var msg = __(
                            "SMS Today: {0} sent, {1} failed, {2} pending",
                            [r.message.sent, r.message.failed, r.message.pending]
                        );
                        frm.dashboard.add_comment(msg, "blue", true);
                    }
                },
            });
        }
    },
});

sms_relay.show_device_health = function () {
    frappe.call({
        method: "sms_relay.api.get_device_health",
        callback: function (r) {
            if (!r.message) return;
            var devices = r.message;
            var html = '<table class="table table-bordered" style="font-size:12px;">';
            html += "<tr><th>Device</th><th>Status</th><th>SIM</th>";
            html += "<th>Sent Today</th><th>Quota</th><th>Last Heartbeat</th></tr>";
            devices.forEach(function (d) {
                var status_cls = d.online ? "green" : "red";
                html += "<tr>";
                html += "<td>" + (d.device_name || d.device) + "</td>";
                html +=
                    '<td><span class="indicator-pill ' +
                    status_cls +
                    '">' +
                    (d.online ? "Online" : "Offline") +
                    "</span></td>";
                html += "<td>" + (d.sim_slot || "-") + "</td>";
                html += "<td>" + d.sent_today + "</td>";
                html += "<td>" + d.quota_remaining + " / " + d.daily_quota + "</td>";
                html += "<td>" + (d.last_heartbeat || "Never") + "</td>";
                html += "</tr>";
            });
            html += "</table>";
            frappe.msgprint({
                title: __("SMS Device Health"),
                indicator: "blue",
                message: html,
            });
        },
    });
};

$(document).on("form-refresh", function (e, frm) {
    if (frm.doctype === "SMS Gateway Settings") {
        frm.add_custom_button(__("Check Device Health"), function () {
            sms_relay.show_device_health();
        });
    }
});
