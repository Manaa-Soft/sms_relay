frappe.ui.form.on('SMS Device', {
    refresh(frm) {
        if (frm.doc.is_online) {
            frm.dashboard.add_indicator(__('Online'), 'green');
        } else if (frm.doc.last_heartbeat) {
            const diff = frappe.datetime.get_diff(frappe.datetime.now_datetime(), frm.doc.last_heartbeat);
            frm.dashboard.add_indicator(__('Offline (last seen {0} days ago)', [diff]), 'red');
        } else {
            frm.dashboard.add_indicator(__('Never connected'), 'orange');
        }

        if (frm.doc.battery_level) {
            let color = frm.doc.battery_level > 50 ? 'green' : frm.doc.battery_level > 20 ? 'orange' : 'red';
            frm.dashboard.add_indicator(__('Battery: {0}%', [frm.doc.battery_level]), color);
        }

        frm.dashboard.add_indicator(__('Sent: {0}/{1}', [frm.doc.sent_today || 0, frm.doc.daily_quota || 200]), 'blue');

        if (frm.doc.device_model) {
            frm.dashboard.set_headline(__('Model: {0}', [frm.doc.device_model]));
        }
        if (frm.doc.carrier_name) {
            frm.dashboard.set_headline(__('Carrier: {0} | SIM: {1}', [frm.doc.carrier_name, frm.doc.sim_phone_number || 'N/A']));
        }

        if (!frm.is_new() && frm.doc.server_url && frm.doc.username) {
            frm.add_custom_button(__('Connect Device'), function() {
                frappe.call({
                    method: 'sms_relay.api.endpoints.connect_device',
                    args: { device_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Connecting to device...'),
                    callback: function(r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({message: __('Device connected!'), indicator: 'green'});
                            frm.reload_doc();
                        } else {
                            frappe.show_alert({message: __('Connection failed: ' + (r.message?.error || 'Unknown')), indicator: 'red'});
                        }
                    }
                });
            }, __('Actions'));

            frm.add_custom_button(__('Send Test SMS'), function() {
                frappe.prompt(
                    [{fieldname: 'phone', fieldtype: 'Data', label: 'Phone Number', reqd: 1, default: frm.doc.sim_phone_number || ''},
                     {fieldname: 'message', fieldtype: 'Small Text', label: 'Message', reqd: 1, default: 'Test SMS from ' + frm.doc.device_name}],
                    function(values) {
                        frappe.call({
                            method: 'sms_relay.api.endpoints.send_sms_now',
                            args: { recipient: values.phone, message: values.message },
                            freeze: true,
                            callback: function(r) {
                                if (r.message && r.message.status === 'sent') {
                                    frappe.show_alert({message: __('SMS sent!'), indicator: 'green'});
                                } else {
                                    frappe.show_alert({message: __('Send failed'), indicator: 'red'});
                                }
                            }
                        });
                    },
                    __('Send Test SMS'),
                    __('Send')
                );
            }, __('Actions'));
        }
    }
});
