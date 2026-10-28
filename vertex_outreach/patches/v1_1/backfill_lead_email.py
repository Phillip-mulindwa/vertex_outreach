# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Leads were named by their email; now any lookup goes through the email column.

	Runs before the model sync adds the unique indexes on email and whatsapp, so blanks
	become NULL (which a unique index allows many of) and every email is filled in first.
	"""
	table = "`tabOutreach Contact`"
	frappe.db.sql(
		f"UPDATE {table} SET `email` = LOWER(`name`) WHERE (`email` IS NULL OR `email` = '') AND `name` LIKE '%%@%%'"
	)
	frappe.db.sql(f"UPDATE {table} SET `email` = NULL WHERE `email` = ''")
	frappe.db.sql(
		f"UPDATE {table} SET `domain` = SUBSTRING_INDEX(`email`, '@', -1) WHERE `email` IS NOT NULL AND (`domain` IS NULL OR `domain` = '')"
	)
	frappe.db.sql(
		f"UPDATE {table} SET `organization` = NULLIF(TRIM(`organization`), '') WHERE `organization` IS NOT NULL"
	)
	if frappe.db.has_column("Outreach Contact", "whatsapp"):
		frappe.db.sql(f"UPDATE {table} SET `whatsapp` = NULL WHERE `whatsapp` = ''")
