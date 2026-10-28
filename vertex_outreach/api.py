# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, now

from vertex_outreach import contacts
from vertex_outreach.contacts import CONTACT, claim_fresh, classify_rows, country_region
from vertex_outreach.identifiers import parse_text

ROLES = ("Outreach User", "Outreach Manager", "System Manager")
MANUAL_SOURCE = "Manual check"
MAX_ITEMS_PER_CHECK = 5000
DEFAULT_COUNTRY_KEY = "outreach_default_country"
TEMPLATE_COLUMNS = ["Company", "Email", "WhatsApp", "Country"]


@frappe.whitelist(methods=["POST"])
def check_leads(text: str, claim: int = 0, default_country: str | None = None):
	"""Check pasted emails and WhatsApp numbers against existing leads; optionally claim the fresh ones.

	`default_country` (a Country) is used for numbers without a country code, and remembered as
	the user's choice. Returns {"results": [{input, type, verdict, matched_on, ...details}],
	"summary": {verdict: count}, "claimed": [names of leads created by this call]}.
	"""
	claim = cint(claim)
	frappe.only_for(ROLES)
	frappe.has_permission(CONTACT, "create" if claim else "read", throw=True)

	region = country_region(default_country)
	if default_country and not region:
		frappe.throw(_("Unknown country {0}").format(default_country))
	if (default_country or "") != (frappe.defaults.get_user_default(DEFAULT_COUNTRY_KEY) or ""):
		frappe.defaults.set_user_default(DEFAULT_COUNTRY_KEY, default_country or "")

	items = parse_text(text or "", region)
	if len(items) > MAX_ITEMS_PER_CHECK:
		frappe.throw(
			_("Too many leads ({0}). Check at most {1} at a time, or use an Email Upload.").format(
				len(items), MAX_ITEMS_PER_CHECK
			)
		)

	infos = classify_rows(items)
	claimed = claim_fresh(items, infos, user=frappe.session.user, source=MANUAL_SOURCE) if claim else []

	results = [
		{
			"input": item.input,
			"type": item.type,
			"email": item.email,
			"whatsapp": item.whatsapp,
			**info,
			"organization": info.get("organization") or item.organization,
		}
		for item, info in zip(items, infos, strict=True)
	]
	summary = {}
	for row in results:
		summary[row["verdict"]] = summary.get(row["verdict"], 0) + 1

	return {"results": results, "summary": summary, "claimed": claimed}


@frappe.whitelist(methods=["POST"])
def check_emails(emails: str, claim: int = 0):
	"""Old name of check_leads, kept for existing API users."""
	return check_leads(emails, claim)


@frappe.whitelist(methods=["POST"])
def mark_contacted(names):
	"""Set Claimed leads to Contacted and stamp last_contacted_on on every given lead."""
	names = frappe.parse_json(names)
	if isinstance(names, str):
		names = [names]
	frappe.only_for(ROLES)
	frappe.has_permission(CONTACT, "write", throw=True)
	contacts.mark_contacted(names, last_contacted_on=now())
	return len(names)


@frappe.whitelist()
def download_template():
	"""An empty XLSX with the columns Email Upload reads."""
	from frappe.utils.xlsxutils import make_xlsx

	frappe.only_for(ROLES)
	frappe.response["filename"] = "outreach-leads-template.xlsx"
	frappe.response["filecontent"] = make_xlsx([TEMPLATE_COLUMNS], "Leads").getvalue()
	frappe.response["type"] = "binary"
