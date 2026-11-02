# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

"""What a checker (Outreach User without a manager role) sees: the Outreach workspace and Check Leads.

Permissions do the real work (DocType perms, workspace and page roles). The hooks here only keep
the desk from offering what a checker can't or shouldn't use.
"""

import frappe
from frappe.desk.utils import slug

OUTREACH_USER = "Outreach User"
ADMIN_ROLES = ("System Manager", "Outreach Manager")
WORKSPACE_ROLE = "System Manager"
OWN_MODULE = "Vertex Outreach"
# Frappe's fallback when a user may open no other workspace; never listed in the sidebar
FALLBACK_WORKSPACE = "Welcome Workspace"
CHECK_LEADS_PAGE = "check-leads"
CHECK_LEADS_ROUTE = f"/app/{CHECK_LEADS_PAGE}"
# What the awesome bar ("Search or type a command") still offers a checker
CHECKER_SEARCH = ("Outreach Contact",)
CHECKER_PAGES = ("check-leads", "print")


def is_checker(user: str | None = None) -> bool:
	"""Outreach User without Outreach Manager or System Manager. Administrator never is."""
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	roles = frappe.get_roles(user)
	return OUTREACH_USER in roles and not any(role in roles for role in ADMIN_ROLES)


def restrict_standard_workspaces() -> list[str]:
	"""Give System Manager to every public workspace outside this app that has no roles yet.

	Idempotent. Run by a patch and after every migrate and app install, because syncing a
	workspace from its app resets its roles. Inserts the Has Role rows directly: saving a
	standard workspace in developer mode would export it into its app.
	"""
	workspaces = [
		ws.name
		for ws in frappe.get_all("Workspace", filters={"public": 1}, fields=["name", "module"])
		if ws.module != OWN_MODULE and ws.name != FALLBACK_WORKSPACE
	]
	with_roles = set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": "Workspace", "parent": ["in", workspaces or [""]]},
			pluck="parent",
		)
	)
	restricted = [ws for ws in workspaces if ws not in with_roles]
	for ws in restricted:
		doc = frappe.get_doc("Workspace", ws)
		doc.append("roles", {"role": WORKSPACE_ROLE}).db_insert()
	if restricted:
		frappe.cache.delete_key("bootinfo")
	return restricted


def after_app_install(app_name: str):
	restrict_standard_workspaces()


def send_checkers_to_check_leads():
	"""before_request: land checkers on Check Leads after logging in.

	Frappe sets the login response's home_page after the on_login and on_session_creation hooks,
	but before before_request hooks."""
	if frappe.request.path != "/api/method/login" and frappe.form_dict.get("cmd") != "login":
		return
	if frappe.local.response.get("message") == "Logged In" and is_checker():
		frappe.local.response["home_page"] = CHECK_LEADS_ROUTE


def trim_checker_boot(bootinfo):
	"""boot_session: keep the awesome bar to the lead list and Check Leads.

	Doesn't change any permission: it stops offering other lists, "New ..." items and pages."""
	if not is_checker():
		return
	user = bootinfo["user"]
	user["can_search"] = [d for d in user["can_search"] if d in CHECKER_SEARCH]
	user["can_create"] = []
	# their own User is shared with them; without this the desk opens /app/user
	user["can_read"] = [d for d in user["can_read"] if d != "User"]
	bootinfo["page_info"] = {name: p for name, p in bootinfo["page_info"].items() if name in CHECKER_PAGES}
	# read by the route guard in checker_routes.js
	bootinfo["checker_routes"] = checker_routes(bootinfo)
	bootinfo["checker_home"] = CHECK_LEADS_PAGE


def checker_routes(bootinfo) -> list[str]:
	"""The first /app/<segment> of every route a checker's desk can open: readable DocTypes, pages, workspaces.

	Anything else the desk would look up as a Page, which needs read permission on Page."""
	routes = {slug(d) for d in bootinfo["user"]["can_read"]}
	routes.update(bootinfo["page_info"])
	routes.update(slug(ws["name"]) for ws in bootinfo.get("allowed_workspaces") or [])
	return sorted(routes)


def user_query_conditions(user: str, doctype: str | None = None) -> str:
	"""permission_query_conditions for User: a checker lists only themselves.

	Desk User's select permission on User otherwise lists every user's name."""
	if is_checker(user):
		return f"`tabUser`.`name` = {frappe.db.escape(user)}"
	return ""
