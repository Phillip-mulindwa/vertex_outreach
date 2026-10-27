// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.provide("vertex_outreach");

vertex_outreach.CHECK_ROLES = ["Outreach User", "System Manager"];

vertex_outreach.VERDICT_COLOURS = {
	FRESH: "green",
	"ALREADY CONTACTED": "orange",
	"SIGNED PARTNER": "blue",
	"DO NOT CONTACT": "red",
	INVALID: "gray",
};

vertex_outreach.can_check_emails = function () {
	return frappe.user.has_role(vertex_outreach.CHECK_ROLES);
};

vertex_outreach.check_emails = function (text, claim, $results) {
	if (!(text || "").trim()) {
		frappe.show_alert({ message: __("Paste some emails first"), indicator: "orange" });
		return Promise.resolve();
	}
	return frappe
		.call({
			method: "vertex_outreach.api.check_emails",
			args: { emails: text, claim: claim ? 1 : 0 },
			freeze: true,
			freeze_message: claim ? __("Checking and claiming...") : __("Checking..."),
		})
		.then((r) => {
			vertex_outreach.render_check_results(r.message, $results);
			if (claim && r.message.claimed.length && window.cur_list?.doctype === "Outreach Contact") {
				cur_list.refresh();
			}
			return r.message;
		});
};

vertex_outreach.render_check_results = function (data, $results) {
	const esc = frappe.utils.escape_html;
	const order = Object.keys(vertex_outreach.VERDICT_COLOURS);
	const summary = order
		.filter((v) => data.summary[v])
		.map(
			(v) =>
				`<span class="indicator-pill ${vertex_outreach.VERDICT_COLOURS[v]}">${esc(
					__(v)
				)}: ${data.summary[v]}</span>`
		)
		.join(" ");
	const fresh = [...new Set(data.results.filter((r) => r.verdict === "FRESH").map((r) => r.email))];

	const rows = data.results
		.map((r) => {
			const colour = vertex_outreach.VERDICT_COLOURS[r.verdict];
			let verdict = `<span class="indicator-pill ${colour}">${esc(__(r.verdict))}</span>`;
			if (r.claimed) verdict += ` <span class="text-muted small">${__("claimed by you")}</span>`;
			const who = r.contacted_by_name ? esc(r.contacted_by_name) : "";
			const when = r.contacted_on ? frappe.datetime.str_to_user(r.contacted_on) : "";
			const upload = r.email_upload
				? `<a href="/app/email-upload/${encodeURIComponent(r.email_upload)}">${esc(r.email_upload)}</a>`
				: "";
			const status = r.status ? esc(__(r.status)) : "";
			const organization = r.organization
				? r.verdict === "SIGNED PARTNER"
					? `<b>${esc(r.organization)}</b>`
					: esc(r.organization)
				: "";
			const normalized =
				r.email && r.email !== r.original ? `<div class="text-muted small">→ ${esc(r.email)}</div>` : "";
			return `<tr>
				<td>${esc(r.original)}${normalized}</td>
				<td>${verdict}</td>
				<td>${organization}</td>
				<td>${status}</td>
				<td>${who}</td>
				<td>${when}</td>
				<td>${r.source ? esc(r.source) : ""}</td>
				<td>${upload}</td>
			</tr>`;
		})
		.join("");

	$results.html(`
		<div class="vo-check-summary" style="margin: var(--margin-md) 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
			<b>${__("{0} checked", [data.results.length])}</b> ${summary}
			${data.claimed.length ? `<span class="text-muted">${__("{0} claimed", [data.claimed.length])}</span>` : ""}
			<button class="btn btn-xs btn-default vo-copy-fresh" style="margin-left: auto;" ${
				fresh.length ? "" : "disabled"
			}>${__("Copy fresh emails")} (${fresh.length})</button>
		</div>
		<div style="overflow-x: auto;">
			<table class="table table-bordered table-sm" style="font-size: var(--text-sm);">
				<thead><tr>
					<th>${__("Email")}</th><th>${__("Verdict")}</th><th>${__("Organization")}</th><th>${__("Status")}</th>
					<th>${__("Contacted by")}</th><th>${__("When")}</th><th>${__("Source")}</th><th>${__("Upload")}</th>
				</tr></thead>
				<tbody>${rows || `<tr><td colspan="8" class="text-muted">${__("No emails found in the text")}</td></tr>`}</tbody>
			</table>
		</div>`);
	$results.find(".vo-copy-fresh").on("click", () => frappe.utils.copy_to_clipboard(fresh.join("\n")));
};

vertex_outreach.show_check_emails_dialog = function () {
	const dialog = new frappe.ui.Dialog({
		title: __("Check Emails"),
		size: "extra-large",
		fields: [
			{
				fieldname: "emails",
				fieldtype: "Long Text",
				label: __("Emails"),
				description: __("Paste one or many emails in any format: commas, new lines or mixed text."),
			},
			{ fieldname: "results", fieldtype: "HTML" },
		],
		primary_action_label: __("Check"),
		primary_action: (values) =>
			vertex_outreach.check_emails(values.emails, false, dialog.fields_dict.results.$wrapper),
		secondary_action_label: __("Check & Claim Fresh"),
		secondary_action: () =>
			vertex_outreach.check_emails(
				dialog.get_value("emails"),
				true,
				dialog.fields_dict.results.$wrapper
			),
	});
	dialog.fields_dict.emails.$input.css("height", "220px");
	dialog.show();
	return dialog;
};
