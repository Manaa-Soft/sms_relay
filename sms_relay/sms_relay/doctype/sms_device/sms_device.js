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
    }
});
