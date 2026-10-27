// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.pages["check-emails"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Check Emails"),
		single_column: true,
	});
	const fields = new frappe.ui.FieldGroup({
		body: page.body,
		fields: [
			{
				fieldname: "emails",
				fieldtype: "Long Text",
				label: __("Emails"),
				description: __("Paste one or many emails in any format: commas, new lines or mixed text."),
			},
			{ fieldname: "results", fieldtype: "HTML" },
		],
	});
	fields.make();
	fields.fields_dict.emails.$input.css("height", "220px");

	const run = (claim) =>
		vertex_outreach.check_emails(fields.get_value("emails"), claim, fields.fields_dict.results.$wrapper);
	page.set_primary_action(__("Check"), () => run(false));
	page.set_secondary_action(__("Check & Claim Fresh"), () => run(true));
};
