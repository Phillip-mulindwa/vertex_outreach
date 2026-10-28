# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe

from vertex_outreach.contacts import CONTACT, country_name
from vertex_outreach.identifiers import normalize_phone


def execute():
	"""Leads now say which country their WhatsApp number is from."""
	for name, whatsapp in frappe.get_all(
		CONTACT,
		filters={"whatsapp": ["is", "set"], "whatsapp_country": ["is", "not set"]},
		fields=["name", "whatsapp"],
		as_list=True,
	):
		if country := country_name(normalize_phone(whatsapp).region):
			frappe.db.set_value(CONTACT, name, "whatsapp_country", country, update_modified=False)
