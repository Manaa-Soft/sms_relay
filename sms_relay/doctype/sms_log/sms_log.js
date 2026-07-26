frappe.listview.get_indicator = function(doc) {
    if (doc.status === 'Delivered') return [__('Delivered'), 'green', 'status,=,Delivered'];
    if (doc.status === 'Sent') return [__('Sent'), 'blue', 'status,=,Sent'];
    if (doc.status === 'Failed') return [__('Failed'), 'red', 'status,=,Failed'];
    if (doc.status === 'Queued') return [__('Queued'), 'orange', 'status,=,Queued'];
    return [doc.status, 'grey'];
};
