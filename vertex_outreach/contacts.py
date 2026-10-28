# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

"""Chunked lookups and duplicate-safe bulk writes for Outreach Contact (labelled Outreach Lead).

A lead is identified by its email or its WhatsApp number, both unique-indexed. Never by its
name (LEAD-##### for new leads, the email for leads made before that) and never by its
organization, which is not unique. Shared by uploads, Check Leads and the lead form so they
all agree on what "already in the system" means.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now, now_datetime
from frappe.utils.caching import request_cache

from vertex_outreach.identifiers import EMAIL, WHATSAPP, LeadInput, email_domain

CONTACT = "Outreach Contact"
SETTINGS = "Outreach Settings"
SIGNED_PARTNER_DOCTYPE = "Signed Partner"
NAME_PREFIX = "LEAD-"
NAME_DIGITS = 5
CHUNK_SIZE = 1000
INSERT_CHUNK_SIZE = 5000

CLAIMED = "Claimed"
CONTACTED = "Contacted"
REPLIED = "Replied"
SIGNED = "Signed Partner"
DO_NOT_CONTACT_STATUSES = ("Unsubscribed", "Bounced")

# Columns written by insert_leads
CONTACT_FIELDS = [
	"name",
	"email",
	"domain",
	"whatsapp",
	"organization",
	"country",
	"status",
	"source",
	"uploaded_by",
	"email_upload",
	"claimed_on",
	"last_contacted_on",
	"signed_on",
	"owner",
	"modified_by",
	"creation",
	"modified",
]
LEAD_FIELDS = [
	"name",
	"email",
	"whatsapp",
	"organization",
	"status",
	"uploaded_by",
	"owner",
	"claimed_on",
	"last_contacted_on",
	"creation",
	"source",
	"email_upload",
]

FRESH = "FRESH"
ALREADY_CONTACTED = "ALREADY CONTACTED"
SIGNED_PARTNER = "SIGNED PARTNER"
DO_NOT_CONTACT = "DO NOT CONTACT"
CONFLICT = "CONFLICT"
EXCLUDED_COUNTRY = "EXCLUDED COUNTRY"
INVALID = "INVALID"

COUNTRY_ALIASES = {"uk": "GB", "usa": "US", "uae": "AE"}


def chunks(items: list, size: int = CHUNK_SIZE):
	for i in range(0, len(items), size):
		yield items[i : i + size]


@request_cache
def countries() -> dict[str, str]:
	"""ISO alpha-2 code -> Country name."""
	return {
		code.upper(): name
		for name, code in frappe.get_all("Country", fields=["name", "code"], as_list=True)
		if code
	}


@request_cache
def _regions_by_name() -> dict[str, str]:
	return {name.lower(): code for code, name in countries().items()}


def country_name(region: str | None) -> str | None:
	return countries().get(region.upper()) if region else None


def country_region(value: str | None) -> str | None:
	"""ISO alpha-2 code for a Country name, a two-letter code or a common alias ("UK")."""
	value = (value or "").strip().lower()
	if not value:
		return None
	if value in COUNTRY_ALIASES:
		return COUNTRY_ALIASES[value]
	if len(value) == 2 and value.upper() in countries():
		return value.upper()
	return _regions_by_name().get(value)


def excluded_regions() -> set[str]:
	settings = frappe.get_cached_doc(SETTINGS)
	return {r for r in (country_region(row.country) for row in settings.excluded_countries) if r}


def find_leads(emails, whatsapps, fields: list[str] = LEAD_FIELDS) -> tuple[dict, dict]:
	"""({email: lead}, {whatsapp: lead}) for existing leads, using chunked indexed lookups only."""
	by_email, by_whatsapp = {}, {}
	for field, values, found in (("email", emails, by_email), ("whatsapp", whatsapps, by_whatsapp)):
		for chunk in chunks(sorted({v for v in values if v})):
			for row in frappe.get_all(CONTACT, filters={field: ["in", chunk]}, fields=fields):
				found[row[field]] = row
	return by_email, by_whatsapp


def classify_rows(items: list[LeadInput]) -> list[dict]:
	"""Verdict plus who/when details for each item, in order.

	An item matches a lead when its email OR its WhatsApp number does. If the email matches one
	lead and the number a different one, it is a CONFLICT for a manager to review. Unmatched items
	in an excluded country are EXCLUDED COUNTRY; other unmatched items are FRESH, with a note
	when other leads share their organization name.
	"""
	leads = [i for i in items if not i.error]
	by_email, by_whatsapp = find_leads([i.email for i in leads], [i.whatsapp for i in leads])
	names = full_names({r.uploaded_by or r.owner for r in (*by_email.values(), *by_whatsapp.values())})
	excluded = excluded_regions()

	results, fresh = [], []
	for item in items:
		if item.error:
			results.append({"verdict": INVALID, "note": _(item.error)})
			continue

		email_lead = by_email.get(item.email) if item.email else None
		whatsapp_lead = by_whatsapp.get(item.whatsapp) if item.whatsapp else None
		if email_lead and whatsapp_lead and email_lead.name != whatsapp_lead.name:
			by_email_details = lead_details(email_lead, names)
			by_whatsapp_details = lead_details(whatsapp_lead, names)
			info = {
				"verdict": CONFLICT,
				"matched_on": f"{EMAIL} + {WHATSAPP}",
				"conflict": [by_email_details, by_whatsapp_details],
				"note": _("Email is on {0}, WhatsApp is on {1}. A manager needs to review this.").format(
					describe_lead(by_email_details), describe_lead(by_whatsapp_details)
				),
			}
		elif lead := email_lead or whatsapp_lead:
			matched = [t for t, found in ((EMAIL, email_lead), (WHATSAPP, whatsapp_lead)) if found]
			info = {
				"verdict": verdict_for_status(lead.status),
				"matched_on": " + ".join(matched),
				**lead_details(lead, names),
			}
			if item.email and lead.email and lead.email != item.email:
				info["note"] = _("The lead has a different email: {0}").format(lead.email)
			elif item.whatsapp and lead.whatsapp and lead.whatsapp != item.whatsapp:
				info["note"] = _("The lead has a different WhatsApp number: {0}").format(lead.whatsapp)
		elif in_excluded := sorted(item.regions & excluded):
			info = {
				"verdict": EXCLUDED_COUNTRY,
				"note": _("Excluded country: {0}").format(
					", ".join(country_name(r) or r for r in in_excluded)
				),
			}
		else:
			info = {"verdict": FRESH}
			if item.organization:
				fresh.append((item.organization, info))
		results.append(info)

	_add_organization_notes(fresh)
	return results


def verdict_for_status(status: str) -> str:
	if status in DO_NOT_CONTACT_STATUSES:
		return DO_NOT_CONTACT
	if status == SIGNED:
		return SIGNED_PARTNER
	return ALREADY_CONTACTED


def lead_details(lead, names: dict[str, str]) -> dict:
	user = lead.uploaded_by or lead.owner
	return {
		"lead": lead.name,
		"status": lead.status,
		"organization": lead.organization,
		"email": lead.email,
		"whatsapp": lead.whatsapp,
		"contacted_by": user,
		"contacted_by_name": names.get(user, user),
		"contacted_on": lead.last_contacted_on or lead.claimed_on or lead.creation,
		"source": lead.source,
		"email_upload": lead.email_upload,
	}


def describe_lead(details: dict) -> str:
	"""e.g. 'LEAD-00012 (Acme Ltd), claimed by Grace Achieng on 3 Nov 2026'"""
	text = details["lead"]
	if details.get("organization"):
		text += f" ({details['organization']})"
	verb = {CLAIMED: _("claimed"), SIGNED: _("signed partner, recorded")}.get(
		details["status"], _("contacted")
	)
	text += ", " + _("{0} by {1}").format(verb, details["contacted_by_name"])
	if details.get("contacted_on"):
		text += " " + _("on {0}").format(getdate(details["contacted_on"]).strftime("%-d %b %Y"))
	return text


def _add_organization_notes(fresh: list[tuple[str, dict]]):
	"""Note on each FRESH item how many leads share its organization name (case-insensitive, trimmed)."""
	if not fresh:
		return
	counts: dict[str, list] = {}
	for chunk in chunks(sorted({org for org, _info in fresh})):
		# The column's collation is case-insensitive, so `in` finds every casing; count in Python,
		# naming the organization as its oldest lead spells it
		for org in frappe.get_all(
			CONTACT, filters={"organization": ["in", chunk]}, pluck="organization", order_by="creation asc"
		):
			entry = counts.setdefault(org.strip().lower(), [0, org.strip()])
			entry[0] += 1
	for org, info in fresh:
		if entry := counts.get(org.strip().lower()):
			count, display = entry
			info["note"] = (
				_("1 other lead named {0}").format(display)
				if count == 1
				else _("{0} other leads named {1}").format(count, display)
			)


def full_names(users) -> dict[str, str]:
	users = sorted(u for u in users if u)
	names = {}
	for chunk in chunks(users):
		for name, full_name in frappe.get_all(
			"User", filters={"name": ["in", chunk]}, fields=["name", "full_name"], as_list=True
		):
			names[name] = full_name or name
	return names


def new_lead_names(count: int) -> list[str]:
	"""Reserve `count` consecutive LEAD-##### names from the same series the form uses."""
	if not count:
		return []
	current = frappe.db.sql("SELECT `current` FROM `tabSeries` WHERE `name` = %s FOR UPDATE", NAME_PREFIX)
	if current and current[0][0] is not None:
		start = int(current[0][0])
		frappe.db.sql(
			"UPDATE `tabSeries` SET `current` = `current` + %s WHERE `name` = %s", (count, NAME_PREFIX)
		)
	else:
		start = 0
		frappe.db.sql("INSERT INTO `tabSeries` (`name`, `current`) VALUES (%s, %s)", (NAME_PREFIX, count))
	return [f"{NAME_PREFIX}{n:0{NAME_DIGITS}d}" for n in range(start + 1, start + count + 1)]


def insert_leads(
	items: list[LeadInput],
	status: str,
	*,
	user: str,
	source: str | None = None,
	email_upload: str | None = None,
	last_contacted_on=None,
	timestamp=None,
) -> list[str | None]:
	"""Insert a lead per item; returns the new lead's name per item, or None where it was not inserted.

	An item is skipped when its email or WhatsApp number already belongs to a lead - one that
	existed before, one another user inserted a moment ago, or an earlier item in `items`.
	The unique indexes decide, so the result is only what this call actually inserted.
	"""
	if not items:
		return []
	ts = timestamp or now()
	names = new_lead_names(len(items))
	rows = (
		(
			name,
			item.email,
			email_domain(item.email) if item.email else None,
			item.whatsapp,
			item.organization,
			country_name(item.region or item.country),
			status,
			source,
			user,
			email_upload,
			ts if status == CLAIMED else None,
			last_contacted_on,
			ts if status == SIGNED else None,
			user,
			user,
			ts,
			ts,
		)
		for name, item in zip(names, items, strict=True)
	)
	bulk_insert_ignore(CONTACT, CONTACT_FIELDS, rows)

	inserted = set()
	for chunk in chunks(names):
		inserted.update(frappe.get_all(CONTACT, filters={"name": ["in", chunk]}, pluck="name"))
	return [name if name in inserted else None for name in names]


def claim_fresh(
	items: list[LeadInput], infos: list[dict], *, user: str, source=None, email_upload=None
) -> list[str]:
	"""Claim every FRESH item as a Claimed lead, updating `infos` in place. Returns the new lead names.

	Items someone else claimed between the check and the insert are classified again, so they
	report who has them instead of being reported as claimed.
	"""
	fresh = [i for i, info in enumerate(infos) if info["verdict"] == FRESH]
	ts = now()
	names = insert_leads(
		[items[i] for i in fresh], CLAIMED, user=user, source=source, email_upload=email_upload, timestamp=ts
	)

	lost = []
	for i, name in zip(fresh, names, strict=True):
		if name:
			infos[i].update(claimed=1, lead=name, status=CLAIMED, contacted_by=user, contacted_on=ts)
		else:
			lost.append(i)
	for i, info in zip(lost, classify_rows([items[i] for i in lost]), strict=True):
		infos[i] = info
	return [n for n in names if n]


def mark_contacted(names: list[str], *, last_contacted_on=None):
	"""Claimed leads become Contacted; with `last_contacted_on`, every lead also gets that date.

	Leads further along (Replied, Signed Partner, ...) keep their status.
	"""
	ts, user = now(), frappe.session.user
	for chunk in chunks(list(names)):
		sets = "`status` = CASE WHEN `status` = %s THEN %s ELSE `status` END, `modified` = %s, `modified_by` = %s"
		set_params = [CLAIMED, CONTACTED, ts, user]
		where = f"`name` IN ({', '.join(['%s'] * len(chunk))})"
		where_params = list(chunk)
		if last_contacted_on:
			sets += ", `last_contacted_on` = %s"
			set_params.append(last_contacted_on)
		else:
			where += " AND `status` = %s"
			where_params.append(CLAIMED)
		frappe.db.sql(f"UPDATE `tab{CONTACT}` SET {sets} WHERE {where}", set_params + where_params)


def mark_leads_signed(
	items: list[LeadInput], *, user: str, source: str | None = None, email_upload: str | None = None
) -> tuple[list[str], list[str], list[LeadInput]]:
	"""Make the lead of every item a Signed Partner, creating it when there is none.

	Existing leads are upgraded whatever their status, keeping their organization when the item
	has none. CONFLICT items are left for a manager. Returns (inserted, upgraded, conflict items).
	"""
	upgrade: dict[str, str | None] = {}
	conflicts: list[LeadInput] = []

	def unmatched(batch: list[LeadInput]) -> list[LeadInput]:
		"""Record matched items in `upgrade`; return the items with no lead."""
		rest = []
		for item, info in zip(batch, classify_rows(batch), strict=True):
			if info["verdict"] == CONFLICT:
				conflicts.append(item)
			elif info.get("lead"):
				upgrade[info["lead"]] = item.organization or upgrade.get(info["lead"])
			elif info["verdict"] != INVALID:
				rest.append(item)
		return rest

	new = unmatched(items)
	names = insert_leads(new, SIGNED, user=user, source=source, email_upload=email_upload)
	inserted = [name for name in names if name]
	# Someone else inserted these between the check and our insert: upgrade their lead instead
	unmatched([item for item, name in zip(new, names, strict=True) if not name])

	upgraded = list(upgrade)
	bulk_update_with_organization(CONTACT, upgraded, upgrade, {"status": SIGNED})
	ts = now()
	for chunk in chunks(upgraded):
		frappe.db.sql(
			f"UPDATE `tab{CONTACT}` SET `signed_on` = %s WHERE `signed_on` IS NULL "
			f"AND `name` IN ({', '.join(['%s'] * len(chunk))})",
			[ts, *chunk],
		)
	return inserted, upgraded, conflicts


def upsert_signed_partner_records(
	partners: dict[str, str | None], *, user: str
) -> tuple[list[str], list[str]]:
	"""Create a Signed Partner record per email, or update its organization. Returns (created, updated)."""
	emails = list(partners)
	known = set()
	for chunk in chunks(emails):
		known.update(frappe.get_all(SIGNED_PARTNER_DOCTYPE, filters={"name": ["in", chunk]}, pluck="name"))
	created = [e for e in emails if e not in known]
	ts = now()
	bulk_insert_ignore(
		SIGNED_PARTNER_DOCTYPE,
		["name", "email", "organization", "signed_on", "owner", "modified_by", "creation", "modified"],
		((e, e, partners[e], getdate(ts), user, user, ts, ts) for e in created),
	)
	updated = [e for e in emails if e in known]
	bulk_update_with_organization(SIGNED_PARTNER_DOCTYPE, [e for e in updated if partners[e]], partners, {})
	return created, updated


def bulk_update_with_organization(doctype: str, names: list[str], organizations: dict, values: dict):
	"""UPDATE in chunks: set `values` on every row, and organization per row where one is given."""
	ts, user = now(), frappe.session.user
	for chunk in chunks(names):
		sets, params = [], []
		for field, value in values.items():
			sets.append(f"`{field}` = %s")
			params.append(value)
		with_org = [n for n in chunk if organizations.get(n)]
		if with_org:
			sets.append(
				"`organization` = CASE `name` "
				+ " ".join(["WHEN %s THEN %s"] * len(with_org))
				+ " ELSE `organization` END"
			)
			for n in with_org:
				params += [n, organizations[n]]
		sets += ["`modified` = %s", "`modified_by` = %s"]
		params += [ts, user]
		frappe.db.sql(
			f"UPDATE `tab{doctype}` SET {', '.join(sets)} WHERE `name` IN ({', '.join(['%s'] * len(chunk))})",
			params + chunk,
		)


def release_stale_claims() -> int:
	"""Daily: delete Claimed leads never contacted within the configured days, so they can be claimed again."""
	days = frappe.db.get_single_value(SETTINGS, "release_claimed_after_days")
	if not days or days <= 0:
		return 0
	cutoff = add_days(now_datetime(), -days)
	names = frappe.db.sql_list(
		f"SELECT `name` FROM `tab{CONTACT}` WHERE `status` = %s AND `last_contacted_on` IS NULL "
		"AND COALESCE(`claimed_on`, `creation`) < %s",
		(CLAIMED, cutoff),
	)
	for chunk in chunks(names):
		frappe.db.delete(CONTACT, {"name": ["in", chunk]})
	return len(names)


def bulk_insert_ignore(doctype: str, fields: list[str], rows):
	"""Insert rows, silently skipping any that would duplicate a primary or unique key.

	frappe.db.bulk_insert(ignore_duplicates=True) is correct but builds every statement
	value-by-value through pypika (~16s for 50k contacts). On MariaDB a parameterized
	multi-row INSERT IGNORE does the same in ~4s.
	"""
	if frappe.db.db_type != "mariadb":
		frappe.db.bulk_insert(doctype, fields, rows, ignore_duplicates=True)
		return

	columns = ", ".join(f"`{f}`" for f in fields)
	placeholder = "(" + ", ".join(["%s"] * len(fields)) + ")"
	rows = list(rows)
	for chunk in chunks(rows, INSERT_CHUNK_SIZE):
		frappe.db.sql(
			f"INSERT IGNORE INTO `tab{doctype}` ({columns}) VALUES " + ", ".join([placeholder] * len(chunk)),
			[value for row in chunk for value in row],
		)
