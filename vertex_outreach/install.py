# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe

ROLES = ("Outreach User", "Outreach Manager")


def ensure_role():
	"""DocType permissions reference these roles, so they must exist before the DocTypes sync."""
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)
