# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe

ROLES = ("Outreach User", "Outreach Manager")
DEFAULT_EXCLUDED_COUNTRIES = ("Uganda", "South Africa")
WEEKLY_REPORT = "Weekly outreach summary"


def ensure_role():
	"""DocType permissions reference these roles, so they must exist before the DocTypes sync."""
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def after_install():
	setup_outreach_settings()
	setup_weekly_report()


def setup_outreach_settings():
	"""Save the defaults once, so the daily release job and excluded countries have values to read."""
	if frappe.db.exists("Singles", {"doctype": "Outreach Settings"}):
		return
	settings = frappe.get_single("Outreach Settings")
	settings.release_claimed_after_days = 14
	for country in DEFAULT_EXCLUDED_COUNTRIES:
		if frappe.db.exists("Country", country):
			settings.append("excluded_countries", {"country": country})
	settings.save(ignore_permissions=True)


def setup_weekly_report():
	"""A disabled weekly Auto Email Report of the Outreach Summary; a manager sets the recipients and enables it."""
	if frappe.db.exists("Auto Email Report", WEEKLY_REPORT):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Auto Email Report",
			"report": "Outreach Summary",
			"user": "Administrator",
			"enabled": 0,
			"frequency": "Weekly",
			"day_of_week": "Monday",
			"format": "HTML",
			"email_to": "",
			"description": "Leads claimed, contacted, replied and signed per user in the last 7 days.",
			"dynamic_date_period": "Weekly",
			"from_date_field": "from_date",
			"to_date_field": "to_date",
			"filters": "{}",
		}
	)
	doc.flags.ignore_mandatory = True  # email_to: the recipient is set by hand
	doc.insert(ignore_permissions=True, set_name=WEEKLY_REPORT)
