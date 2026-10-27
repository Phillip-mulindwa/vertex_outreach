# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe

ROLE = "Outreach User"


def ensure_role():
	"""DocType permissions reference this role, so it must exist before the DocTypes sync."""
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
