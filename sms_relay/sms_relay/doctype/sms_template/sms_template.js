frappe.ui.form.on('SMS Template', {
    refresh(frm) {
        frm.add_custom_button(__('Preview'), function() {
            if (!frm.doc.preview_phone) {
                frappe.msgprint(__('Please enter a Test Phone Number first'));
                return;
            }
            frappe.call({
                method: 'sms_relay.api.endpoints.preview_template',
                args: {
                    template_name: frm.doc.name,
                    phone: frm.doc.preview_phone
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __('SMS Preview'),
                            indicator: 'blue',
                            message: '<pre style="white-space: pre-wrap; word-wrap: break-word;">' + r.message + '</pre>'
                        });
                    }
                }
            });
        }, __('Tools'));

        frm.add_custom_button(__('Send Test SMS'), function() {
            if (!frm.doc.preview_phone) {
                frappe.msgprint(__('Please enter a Test Phone Number first'));
                return;
            }
            frappe.confirm(
                __('Send test SMS to {0}?', [frm.doc.preview_phone]),
                function() {
                    frappe.call({
                        method: 'sms_relay.api.endpoints.send_sms_now',
                        args: {
                            recipient: frm.doc.preview_phone,
                            message: frm.doc.message_template,
                            template: frm.doc.name
                        },
                        callback: function(r) {
                            if (r.message && r.message.success) {
                                frappe.show_alert({message: __('Test SMS sent!'), indicator: 'green'});
                            } else {
                                frappe.show_alert({message: __('Failed: ' + (r.message?.error || 'Unknown')), indicator: 'red'});
                            }
                        }
                    });
                }
            );
        }, __('Tools'));
    }
});
