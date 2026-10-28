// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.listview_settings["Outreach Contact"] = {
	get_indicator(doc) {
		const colours = {
			Claimed: "yellow",
			Contacted: "orange",
			Replied: "green",
			"In Discussion": "cyan",
			"Signed Partner": "blue",
			"Not Interested": "gray",
			Bounced: "red",
			Unsubscribed: "red",
		};
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
	onload(listview) {
		if (vertex_outreach.can_check_leads()) {
			listview.page.add_inner_button(__("Check Leads"), () =>
				vertex_outreach.show_check_leads_dialog()
			);
		}
		listview.page.add_actions_menu_item(
			__("Mark as Contacted"),
			() => {
				const names = listview.get_checked_items(true);
				if (names.length) {
					vertex_outreach.mark_contacted(names).then(() => listview.refresh());
				}
			},
			false
		);
	},
};
