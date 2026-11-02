# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe

from vertex_outreach.contacts import CONTACT, country_name
from vertex_outreach.identifiers import normalize_phone


def execute():
	"""Leads saved through frappe.new_doc (Data Import) got the system country. Clear it where no
	WhatsApp number from that country backs it."""
	system_country = frappe.db.get_default("country")
	if not system_country:
		return
	names = [
		name
		for name, whatsapp in frappe.get_all(
			CONTACT, filters={"country": system_country}, fields=["name", "whatsapp"], as_list=True
		)
		if not whatsapp or country_name(normalize_phone(whatsapp).region) != system_country
	]
	if names:
		frappe.db.set_value(CONTACT, {"name": ["in", names]}, "country", None, update_modified=False)
	print(f"clear_default_lead_country: cleared {system_country} on {len(names)} lead(s)")
