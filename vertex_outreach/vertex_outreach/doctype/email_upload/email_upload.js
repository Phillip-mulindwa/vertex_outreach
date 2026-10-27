// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.ui.form.on("Email Upload", {
	refresh(frm) {
		if (["Queued", "Processing"].includes(frm.doc.status)) {
			frm.set_intro(__("Processing in the background. This form refreshes when it finishes."), "blue");
		} else if (frm.doc.status === "Failed") {
			frm.set_intro(__("Processing failed. See the Error Log in Results."), "red");
		} else {
			frm.set_intro("");
		}
	},
});
