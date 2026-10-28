// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

frappe.provide("vertex_outreach");

vertex_outreach.CHECK_ROLES = ["Outreach User", "Outreach Manager", "System Manager"];
vertex_outreach.DEFAULT_COUNTRY_KEY = "outreach_default_country";

vertex_outreach.VERDICT_COLOURS = {
	FRESH: "green",
	"ALREADY CONTACTED": "orange",
	"SIGNED PARTNER": "blue",
	"DO NOT CONTACT": "red",
	CONFLICT: "yellow",
	"EXCLUDED COUNTRY": "purple",
	INVALID: "gray",
};

vertex_outreach.can_check_leads = function () {
	return frappe.user.has_role(vertex_outreach.CHECK_ROLES);
};
// Old name
vertex_outreach.can_check_emails = vertex_outreach.can_check_leads;

vertex_outreach.check_fields = function () {
	return [
		{
			fieldname: "text",
			fieldtype: "Long Text",
			label: __("Emails and WhatsApp numbers"),
			description: __(
				"Paste emails and numbers in any format. A line with a company, an email and a number becomes one lead."
			),
		},
		{
			fieldname: "default_country",
			fieldtype: "Link",
			options: "Country",
			label: __("Default country"),
			default: frappe.defaults.get_user_default(vertex_outreach.DEFAULT_COUNTRY_KEY) || "",
			description: __("Used for numbers without a country code"),
		},
		{ fieldname: "results", fieldtype: "HTML" },
	];
};

vertex_outreach.check_leads = function (values, claim, $results) {
	if (!(values.text || "").trim()) {
		frappe.show_alert({ message: __("Paste some emails or numbers first"), indicator: "orange" });
		return Promise.resolve();
	}
	return frappe
		.call({
			method: "vertex_outreach.api.check_leads",
			args: { text: values.text, claim: claim ? 1 : 0, default_country: values.default_country || "" },
			freeze: true,
			freeze_message: claim ? __("Checking and claiming...") : __("Checking..."),
		})
		.then((r) => {
			// the server remembers it; keep this session in step without a reload
			frappe.boot.user.defaults[vertex_outreach.DEFAULT_COUNTRY_KEY] = values.default_country || "";
			vertex_outreach.render_check_results(r.message, $results);
			if (claim && r.message.claimed.length && window.cur_list?.doctype === "Outreach Contact") {
				cur_list.refresh();
			}
			return r.message;
		});
};

vertex_outreach.lead_link = function (lead, organization) {
	const esc = frappe.utils.escape_html;
	return `<a href="/app/outreach-contact/${encodeURIComponent(lead)}">${esc(organization || lead)}</a>`;
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
	const fresh = [...new Set(data.results.filter((r) => r.verdict === "FRESH").map((r) => r.input))];
	const translate_parts = (text) =>
		text
			.split(" + ")
			.map((t) => __(t))
			.join(" + ");

	const rows = data.results
		.map((r) => {
			const colour = vertex_outreach.VERDICT_COLOURS[r.verdict];
			let verdict = `<span class="indicator-pill ${colour}">${esc(__(r.verdict))}</span>`;
			if (r.claimed) verdict += ` <span class="text-muted small">${__("claimed by you")}</span>`;

			const normalized = [r.email, r.whatsapp].filter((v) => v && !r.input.includes(v));
			const input =
				esc(r.input) +
				(normalized.length ? `<div class="text-muted small">→ ${esc(normalized.join(", "))}</div>` : "");

			let organization = "";
			if (r.conflict) {
				organization = r.conflict
					.map((c) => `${vertex_outreach.lead_link(c.lead, c.organization)} (${esc(c.contacted_by_name)})`)
					.join("<br>");
			} else if (r.lead) {
				organization = vertex_outreach.lead_link(r.lead, r.organization);
				if (r.verdict === "SIGNED PARTNER") organization = `<b>${organization}</b>`;
			} else if (r.organization) {
				organization = esc(r.organization);
			}

			return `<tr>
				<td>${input}</td>
				<td>${r.type ? esc(translate_parts(r.type)) : ""}</td>
				<td>${verdict}</td>
				<td>${r.matched_on ? esc(translate_parts(r.matched_on)) : ""}</td>
				<td>${organization}</td>
				<td>${r.status ? esc(__(r.status)) : ""}</td>
				<td>${r.contacted_by_name ? esc(r.contacted_by_name) : ""}</td>
				<td>${r.contacted_on ? frappe.datetime.str_to_user(r.contacted_on) : ""}</td>
				<td>${r.note ? esc(r.note) : ""}</td>
			</tr>`;
		})
		.join("");

	$results.html(`
		<div class="vo-check-summary" style="margin: var(--margin-md) 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
			<b>${__("{0} checked", [data.results.length])}</b> ${summary}
			${data.claimed.length ? `<span class="text-muted">${__("{0} claimed", [data.claimed.length])}</span>` : ""}
			<button class="btn btn-xs btn-default vo-copy-fresh" style="margin-left: auto;" ${
				fresh.length ? "" : "disabled"
			}>${__("Copy fresh")} (${fresh.length})</button>
		</div>
		<div style="overflow-x: auto;">
			<table class="table table-bordered table-sm" style="font-size: var(--text-sm);">
				<thead><tr>
					<th>${__("Input")}</th><th>${__("Type")}</th><th>${__("Verdict")}</th><th>${__("Matched on")}</th>
					<th>${__("Organization")}</th><th>${__("Status")}</th><th>${__("Contacted by")}</th>
					<th>${__("When")}</th><th>${__("Note")}</th>
				</tr></thead>
				<tbody>${
					rows ||
					`<tr><td colspan="9" class="text-muted">${__("No emails or numbers found in the text")}</td></tr>`
				}</tbody>
			</table>
		</div>`);
	$results.find(".vo-copy-fresh").on("click", () => frappe.utils.copy_to_clipboard(fresh.join("\n")));
};

vertex_outreach.show_check_leads_dialog = function () {
	const dialog = new frappe.ui.Dialog({
		title: __("Check Leads"),
		size: "extra-large",
		fields: vertex_outreach.check_fields(),
		primary_action_label: __("Check"),
		primary_action: (values) =>
			vertex_outreach.check_leads(values, false, dialog.fields_dict.results.$wrapper),
		secondary_action_label: __("Check & Claim Fresh"),
		secondary_action: () =>
			vertex_outreach.check_leads(dialog.get_values(), true, dialog.fields_dict.results.$wrapper),
	});
	dialog.fields_dict.text.$input.css("height", "220px");
	dialog.show();
	return dialog;
};
// Old name
vertex_outreach.show_check_emails_dialog = vertex_outreach.show_check_leads_dialog;

vertex_outreach.mark_contacted = function (names) {
	return frappe
		.call({
			method: "vertex_outreach.api.mark_contacted",
			args: { names: JSON.stringify(names) },
			freeze: true,
		})
		.then((r) => {
			frappe.show_alert({ message: __("{0} marked as contacted", [r.message]), indicator: "green" });
			return r.message;
		});
};

// Check one lead: separate fields, inline validation and a single result card

vertex_outreach.EMAIL_RE = /^[^\s@<>(),;:"]+@[^\s@<>(),;:"]+\.[a-z]{2,63}$/i;
vertex_outreach.WHATSAPP_HINT = __("Include the country code, or pick the country.");

vertex_outreach.make_single_check = function ($parent) {
	const fields = new frappe.ui.FieldGroup({
		body: $parent,
		fields: [
			{ fieldname: "company", fieldtype: "Data", label: __("Company name") },
			{
				fieldname: "email",
				fieldtype: "Data",
				label: __("Email"),
				placeholder: "name@company.com",
				onchange: () => check_email(),
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "whatsapp_country",
				fieldtype: "Link",
				options: "Country",
				label: __("WhatsApp country"),
				default: frappe.defaults.get_user_default(vertex_outreach.DEFAULT_COUNTRY_KEY) || "",
				onchange: () => check_whatsapp(),
			},
			{
				fieldname: "whatsapp",
				fieldtype: "Data",
				label: __("WhatsApp number"),
				placeholder: __("e.g. 772 123 456"),
				description: vertex_outreach.WHATSAPP_HINT,
				onchange: () => check_whatsapp(),
			},
			{ fieldtype: "Section Break" },
			{ fieldname: "result", fieldtype: "HTML" },
		],
	});
	fields.make();

	const esc = frappe.utils.escape_html;
	const say = (fieldname, text, colour) =>
		fields.set_df_property(
			fieldname,
			"description",
			text ? `<span style="color: var(--${colour}-600)">${esc(text)}</span>` : ""
		);
	const value = (fieldname) => (fields.get_value(fieldname) || "").trim();

	function check_email() {
		const email = value("email");
		if (email && !vertex_outreach.EMAIL_RE.test(email)) {
			say("email", __("That email doesn't look right. Check it for typos, e.g. name@company.com."), "red");
			return false;
		}
		say("email", "");
		return true;
	}

	// Validated by the server's normalizer, the same one claiming uses
	let latest = 0;
	function check_whatsapp() {
		const whatsapp = value("whatsapp");
		if (!whatsapp) {
			fields.set_df_property("whatsapp", "description", vertex_outreach.WHATSAPP_HINT);
			return Promise.resolve(true);
		}
		const call = ++latest;
		return frappe
			.call({
				method: "vertex_outreach.api.validate_whatsapp",
				args: { whatsapp, whatsapp_country: fields.get_value("whatsapp_country") || "" },
			})
			.then((r) => {
				if (call !== latest) return !r.message.error;
				if (r.message.error) {
					say("whatsapp", r.message.error, "red");
					return false;
				}
				say("whatsapp", `→ ${r.message.whatsapp}${r.message.country ? ` (${r.message.country})` : ""}`, "green");
				return true;
			});
	}

	function run(claim) {
		if (!value("email") && !value("whatsapp")) {
			say("email", __("Enter an email or a WhatsApp number."), "red");
			return;
		}
		if (!check_email()) return;
		return check_whatsapp().then((ok) => {
			if (!ok) return;
			return frappe
				.call({
					method: "vertex_outreach.api.check_one",
					args: {
						company: value("company"),
						email: value("email"),
						whatsapp: value("whatsapp"),
						whatsapp_country: fields.get_value("whatsapp_country") || "",
						claim: claim ? 1 : 0,
					},
					freeze: true,
					freeze_message: claim ? __("Checking and claiming...") : __("Checking..."),
				})
				.then((r) => {
					frappe.boot.user.defaults[vertex_outreach.DEFAULT_COUNTRY_KEY] =
						fields.get_value("whatsapp_country") || "";
					vertex_outreach.render_single_result(r.message, fields.fields_dict.result.$wrapper);
					if (r.message.claimed) {
						fields.set_values({ company: "", email: "", whatsapp: "" });
					}
				});
		});
	}

	return { fields, run };
};

vertex_outreach.render_single_result = function (r, $result) {
	const esc = frappe.utils.escape_html;
	const colour = vertex_outreach.VERDICT_COLOURS[r.verdict] || "gray";
	let links = "";
	if (r.conflict) {
		links = r.conflict.map((c) => vertex_outreach.lead_link(c.lead, `${c.lead}: ${c.organization || ""}`)).join(" · ");
	} else if (r.lead) {
		links = vertex_outreach.lead_link(r.lead, __("Open lead {0}", [r.lead]));
	}
	const note = r.note && !r.summary.includes(r.note) ? r.note : "";
	$result.html(`
		<div style="margin-top: var(--margin-md); padding: var(--padding-md) var(--padding-lg);
			border: 1px solid var(--border-color); border-left: 4px solid var(--${colour}-500);
			border-radius: var(--border-radius-md);">
			<div style="font-size: var(--text-lg); font-weight: 600;">${esc(r.summary)}</div>
			${note ? `<div class="text-muted" style="margin-top: 4px;">${esc(note)}</div>` : ""}
			${links ? `<div style="margin-top: 8px;">${links}</div>` : ""}
		</div>`);
};
