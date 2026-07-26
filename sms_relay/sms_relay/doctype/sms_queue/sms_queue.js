frappe.ui.form.on('SMS Queue', {
    refresh(frm) {
        if (frm.doc.status === 'Failed' && frm.doc.retry_count < frm.doc.max_retries) {
            frm.add_custom_button(__('Retry Now'), function() {
                frappe.call({
                    method: 'sms_relay.api.endpoints.retry_sms',
                    args: { queue_name: frm.doc.name },
                    callback: function() {
                        frappe.show_alert({message: __('Re-queued for retry'), indicator: 'green'});
                        frm.reload_doc();
                    }
                });
            });
        }
    }
});
