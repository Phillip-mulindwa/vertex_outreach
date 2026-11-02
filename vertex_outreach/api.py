# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, getdate, now

from vertex_outreach import contacts
from vertex_outreach.contacts import (
	CONFLICT,
	CONTACT,
	EXCLUDED_COUNTRY,
	FRESH,
	INVALID,
	claim_fresh,
	classify_rows,
	country_name,
	country_region,
)
from vertex_outreach.identifiers import (
	EMAIL,
	NEEDS_COUNTRY_CODE,
	WHATSAPP,
	LeadInput,
	normalize_email,
	normalize_phone,
	parse_text,
)

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
	# Checkers may claim without create on Outreach Lead and see who has any lead, so the role
	# is the gate and the lookups and inserts don't apply doctype permissions
	frappe.only_for(ROLES)

	items = parse_text(text or "", _remember_country(default_country))
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
def check_one(
	company: str | None = None,
	email: str | None = None,
	whatsapp: str | None = None,
	whatsapp_country: str | None = None,
	claim: int = 0,
):
	"""Check one lead given as separate fields; with `claim`, claim it as ONE lead if it is fresh.

	Returns the classification details plus "summary" (one sentence for the result card) and
	"claimed" (the new lead's name, if any).
	"""
	claim = cint(claim)
	# see check_leads
	frappe.only_for(ROLES)

	region = _remember_country(whatsapp_country)
	item = LeadInput(input="", organization=(company or "").strip() or None)
	if (email or "").strip():
		item.email = normalize_email(email)
		if not item.email:
			frappe.throw(_("That email doesn't look right. Check it for typos, e.g. name@company.com."))
	if (whatsapp or "").strip():
		phone = normalize_phone(whatsapp, region)
		if not phone.e164:
			frappe.throw(whatsapp_error_message(phone.error, whatsapp_country))
		item.whatsapp, item.region = phone.e164, phone.region
	if not item.email and not item.whatsapp:
		frappe.throw(_("Enter an email or a WhatsApp number."))
	item.input = " ".join(v for v in (item.organization, item.email, item.whatsapp) if v)

	infos = classify_rows([item])
	claimed = claim_fresh([item], infos, user=frappe.session.user, source=MANUAL_SOURCE) if claim else []
	info = infos[0]
	return {
		**info,
		"type": item.type,
		"email": item.email,
		"whatsapp": item.whatsapp,
		"organization": info.get("organization") or item.organization,
		"summary": single_check_summary(item, info),
		"claimed": claimed[0] if claimed else None,
	}


@frappe.whitelist()
def validate_whatsapp(whatsapp: str, whatsapp_country: str | None = None):
	"""The shared normalizer, for checking a number as it is typed: {whatsapp, country} or {error}."""
	frappe.only_for(ROLES)
	phone = normalize_phone(whatsapp or "", country_region(whatsapp_country))
	if not phone.e164:
		return {"error": whatsapp_error_message(phone.error, whatsapp_country)}
	return {"whatsapp": phone.e164, "country": country_name(phone.region)}


def whatsapp_error_message(error: str, whatsapp_country: str | None) -> str:
	if error == NEEDS_COUNTRY_CODE:
		return _("Add the country code (like +256) or pick the WhatsApp country.")
	if whatsapp_country:
		return _("That isn't a valid {0} WhatsApp number. Check the digits and the country.").format(
			_(whatsapp_country)
		)
	return _("That isn't a valid WhatsApp number. Check the digits and the country code.")


def single_check_summary(item: LeadInput, info: dict) -> str:
	"""e.g. 'ALREADY CONTACTED: matched on WhatsApp +256772123456, by Grace Achieng on 12 Oct 2026,
	company Acme Travel'"""
	verdict = _(info["verdict"])
	if info["verdict"] == FRESH:
		if info.get("claimed"):
			return _("FRESH: no match. Claimed by you as {0}.").format(info["lead"])
		return _("FRESH: no match")
	if info["verdict"] in (CONFLICT, EXCLUDED_COUNTRY, INVALID):
		return f"{verdict}: {info.get('note') or ''}".rstrip(": ")

	values = {EMAIL: item.email, WHATSAPP: item.whatsapp}
	matched = " + ".join(f"{_(kind)} {values[kind]}" for kind in info["matched_on"].split(" + "))
	text = _("{0}: matched on {1}").format(verdict, matched)
	if info.get("contacted_by_name"):
		text += ", " + _("by {0}").format(info["contacted_by_name"])
	if info.get("contacted_on"):
		text += " " + _("on {0}").format(getdate(info["contacted_on"]).strftime("%-d %b %Y"))
	if info.get("organization"):
		text += ", " + _("company {0}").format(info["organization"])
	return text


def _remember_country(country: str | None) -> str | None:
	"""ISO code of the chosen Country, saved as the user's default for next time."""
	region = country_region(country)
	if country and not region:
		frappe.throw(_("Unknown country {0}").format(country))
	if (country or "") != (frappe.defaults.get_user_default(DEFAULT_COUNTRY_KEY) or ""):
		frappe.defaults.set_user_default(DEFAULT_COUNTRY_KEY, country or "")
	return region


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
	# per lead: an Outreach User may only write their own
	for name in names:
		frappe.has_permission(CONTACT, "write", doc=name, throw=True)
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
