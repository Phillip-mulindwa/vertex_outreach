# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import csv
import io

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now

from vertex_outreach.emails import FREE_MAIL_DOMAINS, email_domain, extract_text, find_emails

CONTACT = "Outreach Contact"
PARTNER_DOMAIN = "Partner Domain"
CHUNK_SIZE = 1000
INSERT_CHUNK_SIZE = 5000
JOB_TIMEOUT = 60 * 60


class EmailUpload(Document):
	def before_save(self):
		if self.status == "Pending" and self.file:
			self.status = "Queued"
			self.flags.enqueue_processing = True

	def on_update(self):
		if self.flags.enqueue_processing:
			self.flags.enqueue_processing = False
			frappe.enqueue(
				"vertex_outreach.vertex_outreach.doctype.email_upload.email_upload.process_upload",
				queue="long",
				timeout=JOB_TIMEOUT,
				enqueue_after_commit=True,
				job_id=f"email_upload::{self.name}",
				deduplicate=True,
				upload_name=self.name,
			)


def process_upload(upload_name: str):
	doc = frappe.get_doc("Email Upload", upload_name)
	try:
		doc.db_set("status", "Processing", notify=True, commit=True)

		filename, content = _read_attachment(doc)
		emails, invalid_count = find_emails(extract_text(filename, content))
		if not emails:
			frappe.throw(
				_(
					"No valid email addresses were found in {0}. If this is a scanned PDF it has no "
					"readable text - export the original document or run OCR on it first."
				).format(filename)
			)

		handler = {
			"Signed Partners": _process_signed_partners,
			"Already Contacted": _process_already_contacted,
			"Scraped Leads": _process_scraped_leads,
		}[doc.upload_type]
		counts = handler(doc, emails)

		doc.db_set(
			{
				"status": "Done",
				"total_found": len(emails) + invalid_count,
				"invalid_count": invalid_count,
				"error_log": None,
				**counts,
			},
			notify=True,
			commit=True,
		)
	except Exception:
		frappe.db.rollback()
		doc.db_set(
			{"status": "Failed", "error_log": frappe.get_traceback()},
			notify=True,
			commit=True,
		)


def _read_attachment(doc) -> tuple[str, bytes | str]:
	file_name = frappe.db.get_value(
		"File",
		{"file_url": doc.file, "attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
		"name",
	) or frappe.db.get_value("File", {"file_url": doc.file}, "name", order_by="creation desc")
	if not file_name:
		frappe.throw(_("Attached file {0} was not found").format(doc.file))

	file_doc = frappe.get_doc("File", file_name)
	return file_doc.file_name or doc.file, file_doc.get_content()


def _chunks(items: list, size: int = CHUNK_SIZE):
	for i in range(0, len(items), size):
		yield items[i : i + size]


def _existing_contacts(emails: list[str]) -> dict[str, str]:
	"""Map of email -> status for emails already in the database, queried in chunks."""
	existing = {}
	for chunk in _chunks(emails):
		for name, status in frappe.get_all(
			CONTACT, filters={"name": ["in", chunk]}, fields=["name", "status"], as_list=True
		):
			existing[name] = status
	return existing


def _partner_domains(domains: list[str]) -> set[str]:
	found = set()
	for chunk in _chunks(domains):
		found.update(frappe.get_all(PARTNER_DOMAIN, filters={"name": ["in", chunk]}, pluck="name"))
	return found


def _insert_contacts(doc, emails: list[str], status: str, last_contacted_on=None):
	if not emails:
		return
	ts = now()
	user = doc.owner
	fields = [
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
	rows = (
		(
			e,
			e,
			email_domain(e),
			status,
			doc.source,
			user,
			doc.name,
			last_contacted_on,
			user,
			user,
			ts,
			ts,
		)
		for e in emails
	)
	_bulk_insert_ignore(CONTACT, fields, rows)


def _bulk_insert_ignore(doctype: str, fields: list[str], rows):
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
	for chunk in _chunks(rows, INSERT_CHUNK_SIZE):
		frappe.db.sql(
			f"INSERT IGNORE INTO `tab{doctype}` ({columns}) VALUES " + ", ".join([placeholder] * len(chunk)),
			[value for row in chunk for value in row],
		)


def _process_signed_partners(doc, emails: list[str]) -> dict:
	existing = _existing_contacts(emails)
	new = [e for e in emails if e not in existing]
	to_update = [e for e, status in existing.items() if status != "Signed Partner"]

	_insert_contacts(doc, new, "Signed Partner")
	for chunk in _chunks(to_update):
		frappe.db.set_value(CONTACT, {"name": ["in", chunk]}, "status", "Signed Partner")

	domains = sorted({email_domain(e) for e in emails} - FREE_MAIL_DOMAINS)
	known_domains = _partner_domains(domains)
	new_domains = [d for d in domains if d not in known_domains]
	if new_domains:
		ts = now()
		_bulk_insert_ignore(
			PARTNER_DOMAIN,
			["name", "domain", "owner", "modified_by", "creation", "modified"],
			((d, d, doc.owner, doc.owner, ts, ts) for d in new_domains),
		)

	return {
		"new_count": len(new),
		"duplicate_count": len(existing),
		"partner_count": len(new_domains),
		"clean_file": None,
	}


def _process_already_contacted(doc, emails: list[str]) -> dict:
	existing = _existing_contacts(emails)
	new = [e for e in emails if e not in existing]
	_insert_contacts(doc, new, "Contacted")
	return {
		"new_count": len(new),
		"duplicate_count": len(existing),
		"partner_count": 0,
		"clean_file": None,
	}


def _process_scraped_leads(doc, emails: list[str]) -> dict:
	existing = _existing_contacts(emails)
	partner_domains = _partner_domains(sorted({email_domain(e) for e in emails}))

	fresh, partner_count, duplicate_count = [], 0, 0
	for e in emails:
		if existing.get(e) == "Signed Partner" or email_domain(e) in partner_domains:
			partner_count += 1
		elif e in existing:
			duplicate_count += 1
		else:
			fresh.append(e)

	_insert_contacts(doc, fresh, "Contacted", last_contacted_on=now())

	# Another upload running at the same time may have claimed some of these between our
	# check and insert (INSERT IGNORE skips them) - only hand out the ones this upload owns.
	claimed = set()
	for chunk in _chunks(fresh):
		claimed.update(
			frappe.get_all(CONTACT, filters={"name": ["in", chunk], "email_upload": doc.name}, pluck="name")
		)
	lost = len(fresh) - len(claimed)
	fresh = [e for e in fresh if e in claimed]

	clean_file = _attach_clean_csv(doc, fresh) if fresh else None
	return {
		"new_count": len(fresh),
		"duplicate_count": duplicate_count + lost,
		"partner_count": partner_count,
		"clean_file": clean_file,
	}


def _attach_clean_csv(doc, emails: list[str]) -> str:
	buf = io.StringIO()
	writer = csv.writer(buf)
	writer.writerow(["email", "domain"])
	writer.writerows((e, email_domain(e)) for e in emails)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.name}-new-emails.csv",
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"attached_to_field": "clean_file",
			"is_private": 1,
			"content": buf.getvalue(),
		}
	)
	file_doc.insert(ignore_permissions=True)
	return file_doc.file_url
