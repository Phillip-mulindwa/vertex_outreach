// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

// Runs public/js/check_leads.js in Node against a minimal stand-in for the Frappe desk and checks
// that Check Leads sends what the inputs hold now, never values from an earlier check, and only
// ever shows a result for the inputs it was checked against. Prints the payloads it sent as JSON,
// which test_leads.TestCheckLeadsPayload replays through the whitelisted API.
//
//	node vertex_outreach/tests/js/single_check.test.js

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXISTING = { email: "known.lead@vo-payload.example", whatsapp: "+254 712 123 456" };
const NEW_EMAIL = "brand.new@vo-payload.example";

class FakeElement {
	constructor() {
		this.handlers = {};
		this.content = "";
	}
	on(events, handler) {
		for (const event of events.split(" ")) (this.handlers[event] ||= []).push(handler);
		return this;
	}
	trigger(event) {
		for (const handler of this.handlers[event] || []) handler({ type: event });
	}
	html(content) {
		this.content = content;
		return this;
	}
	empty() {
		this.content = "";
		return this;
	}
}

class FieldGroup {
	constructor({ fields }) {
		this.fields = fields;
		this.values = {};
		this.fields_dict = {};
	}
	make() {
		for (const df of this.fields) {
			if (!df.fieldname) continue;
			this.fields_dict[df.fieldname] = { df, $input: new FakeElement(), $wrapper: new FakeElement() };
			if (df.default !== undefined) this.values[df.fieldname] = df.default;
		}
	}
	get_value(fieldname) {
		return this.values[fieldname];
	}
	set_values(values) {
		Object.assign(this.values, values);
		return Promise.resolve();
	}
	set_df_property() {}
}

const calls = [];
const frappe = {
	provide: (name) => (sandbox[name] ||= {}),
	ui: { FieldGroup },
	utils: {
		escape_html: (s) =>
			String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`),
	},
	user: { has_role: (roles) => roles.some((r) => frappe._roles.includes(r)) },
	_roles: ["Outreach User"],
	// A user default from before the remembered country was dropped must not be filled in
	defaults: { get_user_default: () => "Kenya" },
	boot: { user: { defaults: {} } },
	show_alert: () => {},
	call(opts) {
		let resolve;
		const promise = new Promise((r) => (resolve = r));
		calls.push({ method: opts.method, args: JSON.parse(JSON.stringify(opts.args)), respond: (message) => resolve({ message }) });
		return promise;
	},
};
const __ = (text, args) => (args || []).reduce((t, a, i) => t.replace(`{${i}}`, a), text);
const sandbox = { frappe, __, console };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../../public/js/check_leads.js"), "utf8"), sandbox);
const vo = sandbox.vertex_outreach;

const tick = () => new Promise((r) => setImmediate(r));
const last = (method) => calls.filter((c) => c.method === method).at(-1);
const count = (method) => calls.filter((c) => c.method === method).length;

async function main() {
	const single = vo.make_single_check(new FakeElement());
	const { fields } = single;
	const $result = fields.fields_dict.result.$wrapper;
	const type = (fieldname, value) => {
		fields.values[fieldname] = value;
		fields.fields_dict[fieldname].$input.trigger("input");
	};

	// No country is filled in from a remembered default
	assert.strictEqual(fields.get_value("whatsapp_country"), undefined);
	assert.ok(!vo.check_fields().find((df) => df.fieldname === "default_country").default);

	// 1. Check an existing lead: email + WhatsApp
	type("email", EXISTING.email);
	type("whatsapp", EXISTING.whatsapp);
	const first = single.run(false);
	await tick();
	last("vertex_outreach.api.validate_whatsapp").respond({ whatsapp: "+254712123456", country: "Kenya" });
	await tick();
	const stale = last("vertex_outreach.api.check_one");
	assert.deepStrictEqual(stale.args, {
		company: "",
		email: EXISTING.email,
		whatsapp: EXISTING.whatsapp,
		whatsapp_country: "",
		claim: 0,
	});

	// 2. While that is still on its way, the checker types the next lead: a new email, number cleared
	type("email", NEW_EMAIL);
	type("whatsapp", "");
	const second = single.run(false);
	await tick();
	const current = last("vertex_outreach.api.check_one");
	assert.notStrictEqual(current, stale);
	// The payload is what the inputs hold now, not the previous check's values
	assert.deepStrictEqual(current.args, { ...single.current_args(), claim: 0 });
	assert.deepStrictEqual(current.args, {
		company: "",
		email: NEW_EMAIL,
		whatsapp: "",
		whatsapp_country: "",
		claim: 0,
	});

	// 3. The new check answers first, then the old one arrives late: the late answer is dropped
	current.respond({ verdict: "FRESH", summary: "FRESH: no match", checked: { email: NEW_EMAIL } });
	await second;
	assert.match($result.content, /FRESH: no match/);
	stale.respond({
		verdict: "ALREADY CONTACTED",
		summary: "ALREADY CONTACTED — ...",
		proof: [{ matched_on: [["Email", EXISTING.email]], lead: "LEAD-00001", details: " (Old Co)" }],
	});
	await first;
	assert.match($result.content, /FRESH: no match/);
	assert.doesNotMatch($result.content, /ALREADY CONTACTED/);

	// 4. Typing clears a shown result straight away, without waiting for the debounced change
	type("email", NEW_EMAIL + "x");
	assert.strictEqual($result.content, "");

	// 5. A response for inputs that changed while it was on its way is dropped
	type("email", NEW_EMAIL);
	const third = single.run(false);
	await tick();
	const moved = last("vertex_outreach.api.check_one");
	type("email", "someone.else@vo-payload.example");
	moved.respond({ verdict: "FRESH", summary: "FRESH: no match" });
	await third;
	assert.strictEqual($result.content, "");

	// 6. Proof: checkers get the lead ID as text, managers as a link
	const proof = {
		verdict: "ALREADY CONTACTED",
		summary: "ALREADY CONTACTED — ...",
		proof: [{ matched_on: [["Email", "x@y.example"]], lead: "LEAD-00123", details: " (Acme), claimed by Damalie on 2 Nov 2026" }],
	};
	vo.render_single_result(proof, $result);
	assert.match($result.content, /Matched on Email: x@y\.example → LEAD-00123 \(Acme\), claimed by Damalie on 2 Nov 2026/);
	assert.doesNotMatch($result.content, /<a /);
	frappe._roles = ["Outreach User", "Outreach Manager"];
	vo.render_single_result(proof, $result);
	assert.match($result.content, /→ <a href="\/app\/outreach-contact\/LEAD-00123">LEAD-00123<\/a> \(Acme\)/);
	frappe._roles = ["Outreach User"];

	// 7. Check many sends the pasted text and only a country picked for this check
	const before = count("vertex_outreach.api.check_leads");
	vo.check_leads({ text: NEW_EMAIL }, false, new FakeElement());
	assert.strictEqual(count("vertex_outreach.api.check_leads"), before + 1);
	const many = last("vertex_outreach.api.check_leads");
	assert.deepStrictEqual(many.args, { text: NEW_EMAIL, claim: 0, default_country: "" });

	console.log(JSON.stringify({ existing: stale.args, fresh: current.args, many: many.args }));
}

main().catch((e) => {
	console.error(e);
	process.exit(1);
});
