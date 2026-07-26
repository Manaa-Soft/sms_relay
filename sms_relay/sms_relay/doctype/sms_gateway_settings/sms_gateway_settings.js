frappe.ui.form.on('SMS Gateway Settings', {
    refresh(frm) {
        // Show test connection button
        if (!frm.is_new()) {
            frm.add_custom_button(__('Test Connection'), function() {
                frappe.call({
                    method: 'sms_relay.api.endpoints.test_connection',
                    callback: function(r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({message: __('Connection successful!'), indicator: 'green'});
                        } else {
                            frappe.show_alert({message: __('Connection failed: ' + (r.message?.error || 'Unknown')), indicator: 'red'});
                        }
                    }
                });
            });
        }
    }
});
