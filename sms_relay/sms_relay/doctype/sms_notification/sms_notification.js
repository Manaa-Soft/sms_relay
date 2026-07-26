frappe.notification = {
	setup_fieldname_select: function (frm) {
		if (!frm.doc.reference_doctype) {
			return;
		}

		frappe.model.with_doctype(frm.doc.reference_doctype, function () {
			let get_select_options = function (df, parent_field) {
				let select_value = parent_field ? df.fieldname + "," + parent_field : df.fieldname;
				let path = parent_field ? parent_field + " > " + df.fieldname : df.fieldname;

				return {
					value: select_value,
					label: path + " (" + __(df.label, null, df.parent) + ")",
				};
			};

			let fields = frappe.get_doc("DocType", frm.doc.reference_doctype).fields;

			let phone_options = $.map(fields, function (d) {
				return frappe.model.no_value_type.includes(d.fieldtype)
					? null
					: get_select_options(d);
			});
			frm.set_df_property("set_property_after_alert", "options", [""].concat(phone_options));

			let date_options = $.map(fields, function (d) {
				return d.fieldtype === "Date" || d.fieldtype === "Datetime"
					? { value: d.fieldname, label: d.fieldname + " (" + d.label + ")" }
					: null;
			});
			frm.set_df_property("date_changed", "options", [""].concat(date_options));
		});
	},
};


frappe.ui.form.on('SMS Notification', {
	refresh: function(frm) {
		frappe.notification.setup_fieldname_select(frm);
		if (frm.doc.template) {
			frm.trigger("load_template");
		}
	},
	template: function(frm) {
		frm.trigger("load_template");
	},
	load_template: function(frm) {
		if (!frm.doc.template) {
			return;
		}
		frappe.db.get_value(
			"SMS Template",
			frm.doc.template,
			"message_template",
			function(r) {
				if (r && r.message_template) {
					frm.set_value("message_template", r.message_template);
				}
			}
		);
	},
	reference_doctype: function(frm) {
		frappe.notification.setup_fieldname_select(frm);
	},
});
