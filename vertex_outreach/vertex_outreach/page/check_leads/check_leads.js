// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.pages["check-leads"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Check Leads"),
		single_column: true,
	});

	const $tabs = $(`<ul class="nav nav-tabs" style="margin-bottom: var(--margin-md);">
		<li class="nav-item"><a class="nav-link" href="#" data-tab="one">${__("Check one lead")}</a></li>
		<li class="nav-item"><a class="nav-link" href="#" data-tab="many">${__("Check many")}</a></li>
	</ul>`).appendTo(page.body);
	const $one = $('<div data-tab="one"></div>').appendTo(page.body);
	const $many = $('<div data-tab="many"></div>').appendTo(page.body);

	const single = vertex_outreach.make_single_check($one);

	const many = new frappe.ui.FieldGroup({ body: $many, fields: vertex_outreach.check_fields() });
	many.make();
	many.fields_dict.text.$input.css("height", "220px");
	const run_many = (claim) =>
		vertex_outreach.check_leads(many.get_values(), claim, many.fields_dict.results.$wrapper);

	const actions = {
		one: [__("Check"), () => single.run(false), __("Check & Claim"), () => single.run(true)],
		many: [__("Check"), () => run_many(false), __("Check & Claim Fresh"), () => run_many(true)],
	};
	const show = (tab) => {
		$tabs.find(".nav-link").each((_i, a) => $(a).toggleClass("active", a.dataset.tab === tab));
		$one.toggle(tab === "one");
		$many.toggle(tab === "many");
		const [primary, primary_click, secondary, secondary_click] = actions[tab];
		page.set_primary_action(primary, primary_click);
		page.set_secondary_action(secondary, secondary_click);
	};
	$tabs.on("click", ".nav-link", (e) => {
		e.preventDefault();
		show(e.currentTarget.dataset.tab);
	});
	show("one");
};
