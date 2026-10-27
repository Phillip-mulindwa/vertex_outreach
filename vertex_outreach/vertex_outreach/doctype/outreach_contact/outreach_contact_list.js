// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.listview_settings["Outreach Contact"] = {
	get_indicator(doc) {
		const colours = {
			New: "gray",
			Contacted: "orange",
			Replied: "green",
			"Signed Partner": "blue",
			Bounced: "red",
			Unsubscribed: "red",
		};
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
	onload(listview) {
		if (vertex_outreach.can_check_emails()) {
			listview.page.add_inner_button(__("Check Emails"), () =>
				vertex_outreach.show_check_emails_dialog()
			);
		}
	},
};
