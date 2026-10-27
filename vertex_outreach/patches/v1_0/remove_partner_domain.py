# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Partner status now comes only from Outreach Contact.status == "Signed Partner".

	Existing Partner Domain rows were test data, so they are simply deleted with the DocType.
	"""
	if frappe.db.table_exists("Partner Domain"):
		frappe.db.delete("Partner Domain")
	frappe.delete_doc("DocType", "Partner Domain", force=True, ignore_missing=True)
	# delete_doc removes the DocType but not its table during migrate
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabPartner Domain`")
