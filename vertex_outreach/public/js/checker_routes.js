// Copyright (c) 2026, Vertex International Recruitment and contributors
// For license information, please see license.txt

// Send a checker who opens an /app route they can't use (an old link or browser history, e.g.
// /app/user?enabled=1) to Check Leads. Otherwise the desk looks the route up as a Page and shows
// "No permission for Page". frappe.boot.checker_routes is set only for checkers, by
// vertex_outreach.access.trim_checker_boot.
const route = frappe.router.route;

frappe.router.route = function () {
	const allowed = frappe.boot && frappe.boot.checker_routes;
	if (allowed) {
		const first = this.get_sub_path().split("/")[0];
		if (first && !allowed.includes(first)) {
			// replace, so Back doesn't return to the blocked route
			frappe.route_flags.replace_route = true;
			return frappe.set_route(frappe.boot.checker_home);
		}
	}
	return route.apply(this, arguments);
};
