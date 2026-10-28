// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.ui.form.on("Outreach Contact", {
	refresh(frm) {
		if (frm.doc.whatsapp) {
			frm.add_custom_button(__("WhatsApp"), () =>
				window.open(`https://wa.me/${frm.doc.whatsapp.replace(/\D/g, "")}`, "_blank", "noopener")
			);
		}
		if (!frm.is_new() && ["Claimed", "Contacted"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Mark as Contacted"), () =>
				vertex_outreach.mark_contacted([frm.doc.name]).then(() => frm.reload_doc())
			);
		}
	},
});
