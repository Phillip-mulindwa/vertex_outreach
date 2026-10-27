# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

"""Demo data for trying out Vertex Outreach.

	bench --site vertex.localhost execute vertex_outreach.demo.load
	bench --site vertex.localhost execute vertex_outreach.demo.clear

Everything uses reserved example/test domains (RFC 2606), so clear() can find and
remove exactly the demo records and nothing else.
"""

import random
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from vertex_outreach.contacts import (
	CONTACT,
	CONTACT_FIELDS,
	SIGNED_PARTNER_DOCTYPE,
	bulk_insert_ignore,
)

DEMO_SOURCE = "Demo data"

USERS = [
	("grace.achieng@example.com", "Grace", "Achieng"),
	("daniel.okafor@example.com", "Daniel", "Okafor"),
	("amina.hassan@example.com", "Amina", "Hassan"),
]
# Grace also manages the Signed Partner list
MANAGERS = {"grace.achieng@example.com"}

PARTNERS = [
	("lakeside-health.example", "Lakeside Health Group"),
	("summit-academy.example", "Summit Academy Trust"),
	("meridian-care.test", "Meridian Care Homes"),
]

LEAD_DOMAINS = [
	"brightpath-staffing.example",
	"northgate-clinic.example",
	"harbour-nursing.test",
	"oakfield-school.example",
	"riverside-hospital.test",
	"pinecrest-care.example",
	"bluewater-recruit.test",
]
DEMO_DOMAINS = [d for d, _org in PARTNERS] + LEAD_DOMAINS

FIRST = ["james", "olivia", "noah", "ava", "liam", "mia", "ethan", "zara", "lucas", "chloe", "samuel", "ruth"]
LAST = ["smith", "patel", "brown", "nguyen", "wilson", "khan", "taylor", "mensah", "clarke", "ali"]
ROLES = ["hr", "recruitment", "careers", "admin", "info", "talent"]


def load():
	"""Replace any existing demo data with a fresh set."""
	clear()
	rng = random.Random(2026)
	now = now_datetime()

	for email, first, last in USERS:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first,
				"last_name": last,
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": "Outreach User"}]
				+ ([{"role": "Outreach Manager"}] if email in MANAGERS else []),
			}
		)
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)

	def address(domain):
		if rng.random() < 0.4:
			return f"{rng.choice(ROLES)}@{domain}"
		return f"{rng.choice(FIRST)}.{rng.choice(LAST)}@{domain}"

	# (status, count, domain pool)
	plan = [
		("Signed Partner", 6, [d for d, _org in PARTNERS]),
		("Contacted", 22, LEAD_DOMAINS),
		("Replied", 8, LEAD_DOMAINS),
		("Unsubscribed", 4, LEAD_DOMAINS),
	]
	contacts = []  # (email, status, user, contacted_on)
	seen = set()
	for status, count, domains in plan:
		made = 0
		while made < count:
			email = address(rng.choice(domains))
			if email in seen:
				continue
			seen.add(email)
			contacted_on = now - timedelta(days=rng.randint(2, 120), minutes=rng.randint(0, 600))
			contacts.append((email, status, rng.choice(USERS)[0], contacted_on))
			made += 1

	# Two finished uploads: Grace's scraped leads and Daniel's already-contacted list.
	# Every third Contacted/Replied contact came from each upload; the rest were manual.
	specs = [
		("grace.achieng@example.com", "Scraped Leads", "Demo data: agency directory", 34),
		("daniel.okafor@example.com", "Already Contacted", "Demo data: 2025 mail-out", 51),
	]
	batches = {0: [], 1: []}
	for i, contact in enumerate(contacts):
		if contact[1] in ("Contacted", "Replied") and i % 3 in batches:
			batches[i % 3].append(contact[0])
	upload_of = {}
	for i, (owner, upload_type, source, days_ago) in enumerate(specs):
		upload = _make_upload(owner, upload_type, source, now - timedelta(days=days_ago), batches[i])
		upload_of.update({email: upload for email in batches[i]})

	organization_of = dict(PARTNERS)
	rows = []
	for email, status, user, contacted_on in contacts:
		upload = upload_of.get(email)
		if upload:
			user, contacted_on = upload.owner, upload.creation
		rows.append(
			(
				email,
				email,
				email.split("@")[1],
				status,
				upload.source if upload else DEMO_SOURCE,
				user,
				upload.name if upload else None,
				contacted_on,
				user,
				user,
				contacted_on,
				contacted_on,
				organization_of.get(email.split("@")[1]),
			)
		)
	bulk_insert_ignore(CONTACT, CONTACT_FIELDS, rows)

	partners = [r for r in rows if r[3] == "Signed Partner"]
	bulk_insert_ignore(
		SIGNED_PARTNER_DOCTYPE,
		["name", "email", "organization", "signed_on", "notes", "owner", "modified_by", "creation", "modified"],
		[
			(r[0], r[0], r[12], r[7].date(), DEMO_SOURCE, "grace.achieng@example.com", "grace.achieng@example.com", r[7], r[7])
			for r in partners
		],
	)

	frappe.db.commit()
	return {
		"users": [u[0] for u in USERS],
		"signed_partners": len(partners),
		"contacts": len(rows),
		"email_uploads": sorted({u.name for u in upload_of.values()}),
	}


def clear():
	"""Delete only the demo data loaded by load()."""
	uploads = frappe.get_all("Email Upload", filters={"source": ["like", f"{DEMO_SOURCE}%"]}, pluck="name")
	for name in frappe.get_all(
		"File", filters={"attached_to_doctype": "Email Upload", "attached_to_name": ["in", uploads or [""]]}, pluck="name"
	):
		frappe.delete_doc("File", name, ignore_permissions=True, force=True)
	for name in uploads:
		frappe.db.delete("Email Upload", {"name": name})

	contacts = frappe.db.count(CONTACT, {"domain": ["in", DEMO_DOMAINS]})
	frappe.db.delete(CONTACT, {"domain": ["in", DEMO_DOMAINS]})
	partners = 0
	for domain in DEMO_DOMAINS:
		filters = {"name": ["like", f"%@{domain}"]}
		partners += frappe.db.count(SIGNED_PARTNER_DOCTYPE, filters)
		frappe.db.delete(SIGNED_PARTNER_DOCTYPE, filters)

	users = []
	for email, _first, _last in USERS:
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, ignore_permissions=True, force=True)
			users.append(email)

	frappe.db.commit()
	return {"email_uploads": uploads, "users": users, "contacts_deleted": contacts, "signed_partners_deleted": partners}


def _make_upload(owner, upload_type, source, created, emails):
	"""A finished upload with a realistic source file and result counts."""
	content = "email,organization\n" + "".join(f"{e},{e.split('@')[1]}\n" for e in emails)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": source.split(": ")[1].replace(" ", "-") + ".csv",
			"is_private": 1,
			"content": content,
		}
	).insert(ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "Email Upload",
			"upload_type": upload_type,
			"source": source,
			"file": file_doc.file_url,
			"status": "Done",  # not Pending, so saving does not queue processing
			"total_found": len(emails),
			"new_count": len(emails),
		}
	).insert(ignore_permissions=True)
	file_doc.db_set({"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "attached_to_field": "file"})
	frappe.db.set_value(
		doc.doctype,
		doc.name,
		{"owner": owner, "modified_by": owner, "creation": created, "modified": created},
		update_modified=False,
	)
	doc.owner, doc.creation = owner, created
	return doc
