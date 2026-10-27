# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import csv
import io

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now

from vertex_outreach.contacts import (
	claimed_by,
	existing_contacts,
	insert_contacts,
	mark_contacts_signed,
	upsert_signed_partner_records,
)
from vertex_outreach.emails import email_domain, extract_text, find_emails, find_partner_emails

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
		if doc.upload_type == "Signed Partners":
			partners, invalid_count = find_partner_emails(filename, content)
			emails = list(partners)
		else:
			partners = None
			emails, invalid_count = find_emails(extract_text(filename, content))
		if not emails:
			frappe.throw(
				_(
					"No valid email addresses were found in {0}. If this is a scanned PDF it has no "
					"readable text - export the original document or run OCR on it first."
				).format(filename)
			)

		if partners is not None:
			counts = _process_signed_partners(doc, partners)
		else:
			handler = {
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


def _process_signed_partners(doc, partners: dict[str, str | None]) -> dict:
	"""partners: {email: organization or None}. Upgrades/creates contacts and Signed Partner records."""
	new, upgraded = mark_contacts_signed(partners, user=doc.owner, source=doc.source, email_upload=doc.name)
	created, _updated = upsert_signed_partner_records(partners, user=doc.owner)
	return {
		"new_count": len(new),
		"duplicate_count": len(upgraded),
		"partner_count": len(created),
		"clean_file": None,
	}


def _process_already_contacted(doc, emails: list[str]) -> dict:
	existing = existing_contacts(emails)
	new = [e for e in emails if e not in existing]
	insert_contacts(new, "Contacted", user=doc.owner, source=doc.source, email_upload=doc.name)
	return {
		"new_count": len(new),
		"duplicate_count": len(existing),
		"partner_count": 0,
		"clean_file": None,
	}


def _process_scraped_leads(doc, emails: list[str]) -> dict:
	existing = existing_contacts(emails)

	fresh, partner_count, duplicate_count = [], 0, 0
	for e in emails:
		if existing.get(e) == "Signed Partner":
			partner_count += 1
		elif e in existing:
			duplicate_count += 1
		else:
			fresh.append(e)

	insert_contacts(
		fresh, "Contacted", user=doc.owner, source=doc.source, email_upload=doc.name, last_contacted_on=now()
	)

	# Another upload running at the same time may have claimed some of these between our
	# check and insert (INSERT IGNORE skips them) - only hand out the ones this upload owns.
	claimed = claimed_by(fresh, email_upload=doc.name)
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
