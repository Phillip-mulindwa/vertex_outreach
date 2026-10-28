# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import csv
import io

import frappe
from frappe import _
from frappe.model.document import Document

from vertex_outreach.contacts import (
	ALREADY_CONTACTED,
	CLAIMED,
	CONFLICT,
	CONTACTED,
	DO_NOT_CONTACT,
	EXCLUDED_COUNTRY,
	FRESH,
	SIGNED_PARTNER,
	claim_fresh,
	classify_rows,
	country_name,
	country_region,
	insert_leads,
	mark_contacted,
	mark_leads_signed,
	upsert_signed_partner_records,
)
from vertex_outreach.identifiers import LeadInput, parse_file

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
		items = parse_file(
			filename,
			content,
			default_country=country_region(doc.default_country),
			resolve_country=country_region,
		)
		leads = [item for item in items if not item.error]
		if not leads:
			frappe.throw(
				_(
					"No valid email addresses or WhatsApp numbers were found in {0}. If this is a scanned "
					"PDF it has no readable text - export the original document or run OCR on it first."
				).format(filename)
			)

		handler = {
			"Already Contacted": _process_already_contacted,
			"Scraped Leads": _process_scraped_leads,
			"Signed Partners": _process_signed_partners,
		}[doc.upload_type]
		counts = handler(doc, leads)

		doc.db_set(
			{
				"status": "Done",
				"total_found": len(items),
				"invalid_count": len(items) - len(leads),
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


def _process_signed_partners(doc, items: list[LeadInput]) -> dict:
	"""Upgrades/creates leads, and a Signed Partner record per email."""
	inserted, upgraded, conflicts = mark_leads_signed(
		items, user=doc.owner, source=doc.source, email_upload=doc.name
	)
	partners: dict[str, str | None] = {}
	conflict_ids = {id(item) for item in conflicts}
	for item in items:
		if item.email and id(item) not in conflict_ids and not partners.get(item.email):
			partners[item.email] = item.organization
	created, _updated = upsert_signed_partner_records(partners, user=doc.owner)
	return {
		"new_count": len(inserted),
		"duplicate_count": len(upgraded),
		"partner_count": len(created),
		"conflict_count": len(conflicts),
		"excluded_count": 0,
		"clean_file": None,
		"conflict_file": _attach_conflicts(doc, conflicts, classify_rows(conflicts)),
	}


def _process_already_contacted(doc, items: list[LeadInput]) -> dict:
	"""Record every lead not yet in the system as Contacted; Claimed matches become Contacted too."""
	infos = classify_rows(items)
	new = [
		item for item, info in zip(items, infos, strict=True) if info["verdict"] in (FRESH, EXCLUDED_COUNTRY)
	]
	inserted = [
		n for n in insert_leads(new, CONTACTED, user=doc.owner, source=doc.source, email_upload=doc.name) if n
	]
	mark_contacted([info["lead"] for info in infos if info.get("lead") and info["status"] == CLAIMED])

	conflicts = [(item, info) for item, info in zip(items, infos, strict=True) if info["verdict"] == CONFLICT]
	return {
		"new_count": len(inserted),
		"duplicate_count": len(items) - len(inserted) - len(conflicts),
		"partner_count": sum(info["verdict"] == SIGNED_PARTNER for info in infos),
		"conflict_count": len(conflicts),
		"excluded_count": sum(info["verdict"] == EXCLUDED_COUNTRY for info in infos),
		"clean_file": None,
		"conflict_file": _attach_conflicts(doc, *zip(*conflicts, strict=True)) if conflicts else None,
	}


def _process_scraped_leads(doc, items: list[LeadInput]) -> dict:
	"""Claim the fresh leads and hand them out as a clean file."""
	infos = classify_rows(items)
	# Another upload or check running at the same time may claim some of these between our check
	# and insert; claim_fresh reclassifies those, so only leads this upload owns are handed out.
	claim_fresh(items, infos, user=doc.owner, source=doc.source, email_upload=doc.name)

	claimed = [(item, info) for item, info in zip(items, infos, strict=True) if info.get("claimed")]
	conflicts = [(item, info) for item, info in zip(items, infos, strict=True) if info["verdict"] == CONFLICT]
	verdicts = [info["verdict"] for info in infos]
	return {
		"new_count": len(claimed),
		"duplicate_count": verdicts.count(ALREADY_CONTACTED) + verdicts.count(DO_NOT_CONTACT),
		"partner_count": verdicts.count(SIGNED_PARTNER),
		"conflict_count": len(conflicts),
		"excluded_count": verdicts.count(EXCLUDED_COUNTRY),
		"clean_file": _attach_clean_csv(doc, claimed) if claimed else None,
		"conflict_file": _attach_conflicts(doc, *zip(*conflicts, strict=True)) if conflicts else None,
	}


def _attach_clean_csv(doc, claimed: list[tuple[LeadInput, dict]]) -> str:
	return _attach_csv(
		doc,
		"clean_file",
		f"{doc.name}-new-leads.csv",
		["organization", "email", "whatsapp", "country", "lead", "note"],
		(
			(
				item.organization,
				item.email,
				item.whatsapp,
				country_name(item.region or item.country),
				info["lead"],
				info.get("note"),
			)
			for item, info in claimed
		),
	)


def _attach_conflicts(doc, items, infos) -> str | None:
	"""A CSV of rows whose email and WhatsApp number belong to different leads, for a manager."""
	if not items:
		return None
	rows = []
	for item, info in zip(items, infos, strict=True):
		by_email, by_whatsapp = info.get("conflict") or ({}, {})
		rows.append(
			(
				item.input,
				item.organization,
				item.email,
				item.whatsapp,
				by_email.get("lead"),
				by_email.get("organization"),
				by_email.get("contacted_by_name"),
				by_whatsapp.get("lead"),
				by_whatsapp.get("organization"),
				by_whatsapp.get("contacted_by_name"),
			)
		)
	header = [
		"input",
		"organization",
		"email",
		"whatsapp",
		"email_lead",
		"email_lead_organization",
		"email_lead_owner",
		"whatsapp_lead",
		"whatsapp_lead_organization",
		"whatsapp_lead_owner",
	]
	return _attach_csv(doc, "conflict_file", f"{doc.name}-conflicts.csv", header, rows)


def _attach_csv(doc, fieldname: str, file_name: str, header: list[str], rows) -> str:
	buf = io.StringIO()
	writer = csv.writer(buf)
	writer.writerow(header)
	writer.writerows(rows)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"attached_to_field": fieldname,
			"is_private": 1,
			"content": buf.getvalue(),
		}
	)
	file_doc.insert(ignore_permissions=True)
	return file_doc.file_url
