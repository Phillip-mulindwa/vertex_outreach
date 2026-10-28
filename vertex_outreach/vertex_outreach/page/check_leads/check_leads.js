// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.pages["check-leads"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Check Leads"),
		single_column: true,
	});
	const fields = new frappe.ui.FieldGroup({ body: page.body, fields: vertex_outreach.check_fields() });
	fields.make();
	fields.fields_dict.text.$input.css("height", "220px");

	const run = (claim) =>
		vertex_outreach.check_leads(fields.get_values(), claim, fields.fields_dict.results.$wrapper);
	page.set_primary_action(__("Check"), () => run(false));
	page.set_secondary_action(__("Check & Claim Fresh"), () => run(true));
};
