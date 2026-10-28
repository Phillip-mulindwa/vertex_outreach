// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.ui.form.on("Outreach Contact", {
	onload_post_render(frm) {
		// Frappe prefills any field named "country" with the system country. A lead's country
		// comes from the lead (and an excluded one blocks claiming), so don't guess it.
		// Done after the first render: clearing it in onload is undone by the render.
		if (frm.is_new() && frm.doc.country && frm.doc.country === frappe.defaults.get_default("country")) {
			frm.set_value("country", "");
		}
	},
	refresh(frm) {
		if (!frm.is_new() && ["Claimed", "Contacted"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Mark as Contacted"), () =>
				vertex_outreach.mark_contacted([frm.doc.name]).then(() => frm.reload_doc())
			);
		}
	},
	open_whatsapp(frm) {
		window.open(`https://wa.me/${frm.doc.whatsapp.replace(/\D/g, "")}`, "_blank", "noopener");
	},
});
