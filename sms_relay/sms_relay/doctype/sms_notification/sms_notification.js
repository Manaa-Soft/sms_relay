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

			let all_options = $.map(fields, function (d) {
				return frappe.model.no_value_type.includes(d.fieldtype)
					? null
					: get_select_options(d);
			});
			frm.set_df_property("set_property_after_alert", "options", [""].concat(all_options));

			let date_options = $.map(fields, function (d) {
				return d.fieldtype === "Date" || d.fieldtype === "Datetime"
					? { value: d.fieldname, label: d.fieldname + " (" + d.label + ")" }
					: null;
			});
			frm.set_df_property("date_changed", "options", [""].concat(date_options));

			if (frm.doc.fields && frm.doc.fields.length > 0) {
				let param_options = $.map(fields, function (d) {
					return frappe.model.no_value_type.includes(d.fieldtype)
						? null
						: { value: d.fieldname, label: d.fieldname + " (" + d.label + ")" };
				});
				for (let row of frm.doc.fields) {
					frm.fields_dict.fields.grid.grid_rows_by_docname[row.name]
						?.grid_fields
						?.find(f => f.fieldname === "field_name")
						&& frm.set_df_property("field_name", "options", param_options, row.name);
				}
			}
		});
	},

	setup_recipient_field_options: function (frm) {
		if (!frm.doc.reference_doctype) {
			return;
		}

		frappe.model.with_doctype(frm.doc.reference_doctype, function () {
			let is_phone_field = function (df) {
				if (df.fieldtype !== "Data") {
					return false;
				}
				return (
					df.options === "Phone" ||
					df.options === "Mobile" ||
					/mobile|phone/i.test(df.fieldname)
				);
			};

			let get_select_options = function (df, parent_field) {
				let select_value = parent_field ? df.fieldname + "," + parent_field : df.fieldname;
				let path = parent_field ? parent_field + " > " + df.fieldname : df.fieldname;
				return {
					value: select_value,
					label: path + " (" + __(df.label, null, df.parent) + ")",
				};
			};

			let fields = frappe.get_doc("DocType", frm.doc.reference_doctype).fields;

			let extract = function (df) {
				if (frappe.model.table_fields.includes(df.fieldtype)) {
					let child_fields = frappe.get_doc("DocType", df.options).fields;
					return $.map(child_fields, function (cdf) {
						return is_phone_field(cdf) ? get_select_options(cdf, df.fieldname) : null;
					});
				}
				return is_phone_field(df) ? get_select_options(df) : null;
			};

			let options = $.map(fields, extract);
			frm.fields_dict.recipients.grid.update_docfield_property(
				"receiver_by_document_field",
				"options",
				[""].concat(options)
			);
		});
	},

	set_up_filters_editor: function (frm) {
		let parent = frm.get_field("filters_editor").$wrapper;
		parent.empty();

		if (!frm.doc.reference_doctype || frm.doc.condition_type !== "Filters") {
			return;
		}

		let filters =
			frm.doc.filters && frm.doc.filters !== "[]" ? JSON.parse(frm.doc.filters) : [];

		frappe.model.with_doctype(frm.doc.reference_doctype, function () {
			let filter_group = new frappe.ui.FilterGroup({
				parent: parent,
				doctype: frm.doc.reference_doctype,
				on_change: function () {
					frm.set_value("filters", JSON.stringify(filter_group.get_filters()));
				},
			});

			filter_group.add_filters_to_filter_group(filters);
		});
	},

	populate_template_params: function (frm) {
		if (!frm.doc.template || !frm.doc.reference_doctype) {
			return;
		}
		frappe.db.get_value("SMS Template", frm.doc.template, "message_template", function(r) {
			if (!r || !r.message_template) return;
			let matches = r.message_template.match(/\{\{(\d+)\}\}/g);
			if (!matches || matches.length === 0) return;

			let count = matches.reduce((max, m) => {
				let n = parseInt(m.replace(/\{\{|\}\}/g, ""));
				return n > max ? n : max;
			}, 0);

			frappe.model.with_doctype(frm.doc.reference_doctype, function () {
				let fields = frappe.get_doc("DocType", frm.doc.reference_doctype).fields;
				let param_options = $.map(fields, function (d) {
					return frappe.model.no_value_type.includes(d.fieldtype)
						? null
						: { value: d.fieldname, label: d.fieldname + " (" + d.label + ")" };
				});

				let existing = (frm.doc.fields || []).length;
				if (count > existing) {
					for (let i = existing; i < count; i++) {
						let row = frm.add_child("fields", { field_name: "" });
					}
					frm.refresh_field("fields");
				}
			});
		});
	},
};


frappe.ui.form.on('SMS Notification', {
	refresh: function(frm) {
		frappe.notification.setup_fieldname_select(frm);
		frappe.notification.setup_recipient_field_options(frm);
		frappe.notification.set_up_filters_editor(frm);
		let is_parameter = frm.doc.template_type === "Parameter";
		frm.toggle_display("section_break_fields", is_parameter);
		frm.toggle_display("fields", is_parameter);
		if (frm.doc.template) {
			frm.trigger("load_template");
		}

		if (!frm.is_new() && frm.doc.template) {
			frm.add_custom_button(__('Preview Message'), function() {
				frappe.call({
					method: 'sms_relay.api.endpoints.get_notification_preview',
					args: {
						notification_name: frm.doc.name
					},
					callback: function(r) {
						if (r.message && r.message.message) {
							frappe.msgprint({
								title: __('SMS Preview'),
								indicator: 'blue',
								message: '<pre style="white-space: pre-wrap; word-wrap: break-word;">' + frappe.utils.escape_html(r.message.message) + '</pre>'
							});
						} else {
							frappe.show_alert({message: __('No preview available'), indicator: 'orange'});
						}
					}
				});
			}, __('Tools'));
		}
	},
	template: function(frm) {
		frm.trigger("load_template");
		frappe.notification.populate_template_params(frm);
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
		frappe.notification.setup_recipient_field_options(frm);
		frappe.notification.set_up_filters_editor(frm);
	},
	template_type: function(frm) {
		let is_parameter = frm.doc.template_type === "Parameter";
		frm.toggle_display("section_break_fields", is_parameter);
		frm.toggle_display("fields", is_parameter);
	},
	condition_type: function(frm) {
		if (frm.doc.condition_type === "Filters") {
			frm.set_value("condition", "");
		} else {
			frm.set_value("filters", "");
		}
		frappe.notification.set_up_filters_editor(frm);
	},
});

frappe.ui.form.on('SMS Message Field', {
	field_name: function(frm, cdt, cdn) {
		frappe.notification.setup_fieldname_select(frm);
	}
});
