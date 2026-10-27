# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

"""Chunked lookups and duplicate-safe bulk writes for Outreach Contact.

Shared by uploads, the instant email check and manual entry so they all agree on
what "already in the system" means.
"""

import frappe
from frappe import _
from frappe.utils import getdate, now

from vertex_outreach.emails import email_domain

CONTACT = "Outreach Contact"
PARTNER_DOMAIN = "Partner Domain"
CHUNK_SIZE = 1000
INSERT_CHUNK_SIZE = 5000

CONTACT_FIELDS = [
	"name",
	"email",
	"domain",
	"status",
	"source",
	"uploaded_by",
	"email_upload",
	"last_contacted_on",
	"owner",
	"modified_by",
	"creation",
	"modified",
]


def chunks(items: list, size: int = CHUNK_SIZE):
	for i in range(0, len(items), size):
		yield items[i : i + size]


def existing_contacts(emails: list[str], fields: list[str] | None = None) -> dict:
	"""Map of email -> status (or -> row dict when `fields` is given), queried in chunks."""
	existing = {}
	for chunk in chunks(emails):
		if fields:
			for row in frappe.get_all(CONTACT, filters={"name": ["in", chunk]}, fields=["name", *fields]):
				existing[row.name] = row
		else:
			for name, status in frappe.get_all(
				CONTACT, filters={"name": ["in", chunk]}, fields=["name", "status"], as_list=True
			):
				existing[name] = status
	return existing


def partner_domains(domains) -> set[str]:
	domains = sorted(set(domains))
	found = set()
	for chunk in chunks(domains):
		found.update(frappe.get_all(PARTNER_DOMAIN, filters={"name": ["in", chunk]}, pluck="name"))
	return found


def insert_contacts(
	emails: list[str],
	status: str,
	*,
	user: str,
	source: str | None = None,
	email_upload: str | None = None,
	last_contacted_on=None,
	timestamp=None,
):
	"""Bulk insert contacts, skipping any email that already exists. Returns the timestamp used."""
	ts = timestamp or now()
	if emails:
		rows = (
			(
				e,
				e,
				email_domain(e),
				status,
				source,
				user,
				email_upload,
				last_contacted_on,
				user,
				user,
				ts,
				ts,
			)
			for e in emails
		)
		bulk_insert_ignore(CONTACT, CONTACT_FIELDS, rows)
	return ts


def claimed_by(emails: list[str], **filters) -> set[str]:
	"""Which of `emails` exist with the given field values - i.e. which an insert actually won."""
	claimed = set()
	for chunk in chunks(emails):
		claimed.update(frappe.get_all(CONTACT, filters={"name": ["in", chunk], **filters}, pluck="name"))
	return claimed


def bulk_insert_ignore(doctype: str, fields: list[str], rows):
	"""Insert rows, silently skipping any whose primary key already exists.

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


FRESH = "FRESH"
ALREADY_CONTACTED = "ALREADY CONTACTED"
SIGNED_PARTNER = "SIGNED PARTNER"
DO_NOT_CONTACT = "DO NOT CONTACT"
INVALID = "INVALID"

DO_NOT_CONTACT_STATUSES = ("Unsubscribed", "Bounced")
DETAIL_FIELDS = ["status", "uploaded_by", "owner", "last_contacted_on", "creation", "source", "email_upload"]


def classify_emails(emails: list[str]) -> dict[str, dict]:
	"""Verdict plus who/when details for normalized emails, using chunked lookups only."""
	existing = existing_contacts(emails, fields=DETAIL_FIELDS)
	blocked = partner_domains(email_domain(e) for e in emails)
	names = full_names({r.uploaded_by or r.owner for r in existing.values()})

	result = {}
	for email in emails:
		domain = email_domain(email)
		row = existing.get(email)
		if row and row.status in DO_NOT_CONTACT_STATUSES:
			verdict = DO_NOT_CONTACT
		elif (row and row.status == "Signed Partner") or domain in blocked:
			verdict = SIGNED_PARTNER
		elif row:
			verdict = ALREADY_CONTACTED
		else:
			verdict = FRESH

		info = {"verdict": verdict, "partner_domain": domain if domain in blocked else None}
		if row:
			user = row.uploaded_by or row.owner
			info.update(
				status=row.status,
				contacted_by=user,
				contacted_by_name=names.get(user, user),
				contacted_on=row.last_contacted_on or row.creation,
				source=row.source,
				email_upload=row.email_upload,
			)
		result[email] = info
	return result


def full_names(users) -> dict[str, str]:
	users = sorted(u for u in users if u)
	names = {}
	for chunk in chunks(users):
		for name, full_name in frappe.get_all(
			"User", filters={"name": ["in", chunk]}, fields=["name", "full_name"], as_list=True
		):
			names[name] = full_name or name
	return names


def describe_existing(info: dict) -> str:
	"""e.g. 'Already contacted on 12 Oct 2026 by Grace Achieng (status: Contacted, upload UPL-00004)'"""
	when = getdate(info["contacted_on"]).strftime("%-d %b %Y") if info.get("contacted_on") else None
	details = _("status: {0}").format(_(info["status"]))
	if info.get("email_upload"):
		details += ", " + _("upload {0}").format(info["email_upload"])
	if when:
		return _("Already contacted on {0} by {1} ({2})").format(when, info["contacted_by_name"], details)
	return _("Already contacted by {0} ({1})").format(info["contacted_by_name"], details)
