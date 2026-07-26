frappe.ui.form.on('SMS Device', {
    refresh(frm) {
        if (frm.doc.last_heartbeat) {
            const diff = frappe.datetime.get_diff(frappe.datetime.now_datetime(), frm.doc.last_heartbeat);
            if (diff > 5) {
                frm.dashboard.add_indicator(__('Offline (last seen {0} min ago)', [diff]), 'red');
            } else {
                frm.dashboard.add_indicator(__('Online'), 'green');
            }
        }
        frm.dashboard.add_indicator(__('Sent today: {0}/{1}', [frm.doc.sent_today || 0, frm.doc.daily_quota || 200]), 'blue');

        if (!frm.is_new() && frm.doc.server_url && frm.doc.username) {
            frm.add_custom_button(__('Connect Device'), function() {
                frappe.call({
                    method: 'sms_relay.api.endpoints.connect_device',
                    args: { device_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Connecting to device...'),
                    callback: function(r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({message: __('Device connected successfully!'), indicator: 'green'});
                            frm.reload_doc();
                        } else {
                            frappe.show_alert({message: __('Connection failed: ' + (r.message?.error || 'Unknown')), indicator: 'red'});
                        }
                    }
                });
            }, __('Actions'));
        }
    }
});
