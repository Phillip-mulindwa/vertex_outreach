# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe.model.naming import make_autoname
from frappe.model.rename_doc import rename_doc


def execute():
	"""Signed Partners were named by their email; give them SP-##### names, oldest first.

	rename_doc moves comments, versions, attachments and any Link fields along with the record.
	"""
	for name in frappe.get_all(
		"Signed Partner", filters={"name": ["not like", "SP-%"]}, pluck="name", order_by="creation asc"
	):
		rename_doc(
			doctype="Signed Partner",
			old=name,
			new=make_autoname("SP-.#####", "Signed Partner"),
			force=True,
			ignore_permissions=True,
			show_alert=False,
			rebuild_search=False,
		)
