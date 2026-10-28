# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe

from vertex_outreach.install import setup_outreach_settings, setup_weekly_report


def execute():
	# "New" is gone: a lead someone took but has not contacted yet is "Claimed"
	frappe.db.sql(
		"UPDATE `tabOutreach Contact` SET `status` = 'Claimed', `claimed_on` = COALESCE(`claimed_on`, `creation`) "
		"WHERE `status` = 'New' OR `status` IS NULL OR `status` = ''"
	)
	# Check Emails became Check Leads
	frappe.delete_doc("Page", "check-emails", force=True, ignore_missing=True)
	setup_outreach_settings()
	setup_weekly_report()
