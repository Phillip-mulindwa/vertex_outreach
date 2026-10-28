# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

"""Demo data for trying out Vertex Outreach.

	bench --site vertex.localhost execute vertex_outreach.demo.load
	bench --site vertex.localhost execute vertex_outreach.demo.clear

Emails use reserved example/test domains (RFC 2606), and every demo lead has a "Demo data"
source, so clear() can find and remove exactly the demo records and nothing else. load()
returns a `try_in_check_leads` text that shows every verdict, including a CONFLICT.
"""

import random
from datetime import timedelta

import frappe
import phonenumbers
from frappe.utils import now_datetime

from vertex_outreach.contacts import (
	CONTACT,
	SIGNED_PARTNER_DOCTYPE,
	bulk_insert_ignore,
	chunks,
	country_name,
	new_lead_names,
)

DEMO_SOURCE = "Demo data"

USERS = [
	("grace.achieng@example.com", "Grace", "Achieng"),
	("daniel.okafor@example.com", "Daniel", "Okafor"),
	("amina.hassan@example.com", "Amina", "Hassan"),
]
# Grace also manages the Signed Partner list
MANAGER = "grace.achieng@example.com"

PARTNERS = [
	("lakeside-health.example", "Lakeside Health Group"),
	("summit-academy.example", "Summit Academy Trust"),
	("meridian-care.test", "Meridian Care Homes"),
]

# Several leads per company: company names are shared, identifiers never are
LEAD_COMPANIES = [
	("brightpath-staffing.example", "Brightpath Staffing"),
	("northgate-clinic.example", "Northgate Clinic"),
	("harbour-nursing.test", "Harbour Nursing"),
	("oakfield-school.example", "Oakfield School"),
	("riverside-hospital.test", "Riverside Hospital"),
	("pinecrest-care.example", "Pinecrest Care"),
	("bluewater-recruit.test", "Bluewater Recruitment"),
]
DEMO_DOMAINS = [d for d, _org in PARTNERS + LEAD_COMPANIES]

# WhatsApp numbers come from these countries; Uganda and South Africa are excluded by default
REGIONS = ["KE", "NG", "GH", "GB", "RW"]

FIRST = ["james", "olivia", "noah", "ava", "liam", "mia", "ethan", "zara", "lucas", "chloe", "samuel", "ruth"]
LAST = ["smith", "patel", "brown", "nguyen", "wilson", "khan", "taylor", "mensah", "clarke", "ali"]
ROLES = ["hr", "recruitment", "careers", "admin", "info", "talent"]

FIELDS = [
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
	"replied_on",
	"signed_on",
	"owner",
	"modified_by",
	"creation",
	"modified",
]


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
				+ ([{"role": "Outreach Manager"}] if email == MANAGER else []),
			}
		)
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)

	numbers = _numbers(rng)
	seen = set()

	def address(domain):
		while True:
			if rng.random() < 0.4:
				email = f"{rng.choice(ROLES)}@{domain}"
			else:
				email = f"{rng.choice(FIRST)}.{rng.choice(LAST)}@{domain}"
			if email not in seen:
				seen.add(email)
				return email

	# (status, count, companies, share with a WhatsApp number, share with no email, (min, max) days ago)
	plan = [
		("Signed Partner", 6, PARTNERS, 0.5, 0, (30, 200)),
		("Contacted", 20, LEAD_COMPANIES, 0.5, 0.15, (2, 120)),
		("Replied", 6, LEAD_COMPANIES, 0.6, 0, (5, 90)),
		("In Discussion", 3, LEAD_COMPANIES, 1, 0, (5, 60)),
		("Not Interested", 2, LEAD_COMPANIES, 0, 0, (10, 90)),
		("Unsubscribed", 3, LEAD_COMPANIES, 0, 0, (10, 120)),
		("Claimed", 5, LEAD_COMPANIES, 0.5, 0.2, (0, 10)),
		# never contacted: the daily job releases these
		("Claimed", 2, LEAD_COMPANIES, 0.5, 0, (16, 30)),
	]
	leads = []  # dicts in FIELDS order, without name
	for status, count, companies, with_whatsapp, without_email, (newest, oldest) in plan:
		for _i in range(count):
			domain, organization = rng.choice(companies)
			whatsapp, region = next(numbers) if rng.random() < with_whatsapp else (None, None)
			email = None if whatsapp and rng.random() < without_email else address(domain)
			if not email and not whatsapp:
				email = address(domain)
			when = now - timedelta(days=rng.randint(newest, oldest), minutes=rng.randint(0, 600))
			leads.append(
				_lead(email, whatsapp, region, organization, status, rng.choice(USERS)[0], when, rng)
			)

	# The conflict case: an email on one lead and a number on another
	conflict_email = _lead(
		"hr@northgate-clinic.example",
		None,
		None,
		"Northgate Clinic",
		"Contacted",
		USERS[0][0],
		now - timedelta(days=20),
		rng,
	)
	conflict_number, region = next(numbers)
	conflict_whatsapp = _lead(
		"info@harbour-nursing.test",
		conflict_number,
		region,
		"Harbour Nursing",
		"Replied",
		USERS[1][0],
		now - timedelta(days=12),
		rng,
	)
	leads = [
		lead
		for lead in leads
		if lead["email"] not in ("hr@northgate-clinic.example", "info@harbour-nursing.test")
	]
	leads += [conflict_email, conflict_whatsapp]
	# A number someone already messaged, to match with a different email
	matched_by_whatsapp = next(lead for lead in leads if lead["whatsapp"] and lead["status"] == "Contacted")

	# Two finished uploads: Grace's scraped leads and Daniel's already-contacted list.
	# Every third Contacted/Replied lead with an email came from each upload; the rest were manual.
	specs = [
		("grace.achieng@example.com", "Scraped Leads", "Demo data: agency directory", 34),
		("daniel.okafor@example.com", "Already Contacted", "Demo data: 2025 mail-out", 51),
	]
	batches = {0: [], 1: []}
	for i, lead in enumerate(leads):
		if lead["status"] in ("Contacted", "Replied") and lead["email"] and i % 3 in batches:
			batches[i % 3].append(lead)
	for i, (owner, upload_type, source, days_ago) in enumerate(specs):
		upload = _make_upload(owner, upload_type, source, now - timedelta(days=days_ago), batches[i])
		for lead in batches[i]:
			when = upload.creation
			lead.update(
				source=source, email_upload=upload.name, uploaded_by=owner, owner=owner, modified_by=owner
			)
			lead.update(creation=when, modified=when, last_contacted_on=when)
			lead["claimed_on"] = when if upload_type == "Scraped Leads" else None

	leads.sort(key=lambda lead: lead["creation"])
	for name, lead in zip(new_lead_names(len(leads)), leads, strict=True):
		lead["name"] = name
	bulk_insert_ignore(CONTACT, FIELDS, [tuple(lead[f] for f in FIELDS) for lead in leads])

	partners = [lead for lead in leads if lead["status"] == "Signed Partner" and lead["email"]]
	bulk_insert_ignore(
		SIGNED_PARTNER_DOCTYPE,
		[
			"name",
			"email",
			"organization",
			"signed_on",
			"notes",
			"owner",
			"modified_by",
			"creation",
			"modified",
		],
		[
			(
				p["email"],
				p["email"],
				p["organization"],
				p["signed_on"].date(),
				DEMO_SOURCE,
				MANAGER,
				MANAGER,
				p["signed_on"],
				p["signed_on"],
			)
			for p in partners
		],
	)

	frappe.db.commit()
	try_in_check_leads = "\n".join(
		[
			f"Northgate Clinic, hr@northgate-clinic.example, {conflict_number}",  # CONFLICT
			f"new.person@brightpath-staffing.example {matched_by_whatsapp['whatsapp']}",  # matched on WhatsApp
			"Oakfield School: deputy.head@oakfield-new.example",  # FRESH, shares a company name
			f"{partners[0]['email']}",  # SIGNED PARTNER
			"Kampala Agency +256 772 123456",  # EXCLUDED COUNTRY (phone)
			"jobs@joburg-staffing.co.za",  # EXCLUDED COUNTRY (email)
			"0712 123456",  # INVALID without a default country, FRESH (Kenya) with one
			"brand.new@fresh-agency.example",  # FRESH
		]
	)
	return {
		"users": [u[0] for u in USERS],
		"leads": len(leads),
		"with_whatsapp": sum(bool(lead["whatsapp"]) for lead in leads),
		"signed_partners": len(partners),
		"stale_claims": sum(
			lead["status"] == "Claimed" and lead["claimed_on"] < now - timedelta(days=14) for lead in leads
		),
		"try_in_check_leads": try_in_check_leads,
	}


def clear():
	"""Delete only the demo data loaded by load()."""
	uploads = frappe.get_all("Email Upload", filters={"source": ["like", f"{DEMO_SOURCE}%"]}, pluck="name")
	for name in frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Email Upload", "attached_to_name": ["in", uploads or [""]]},
		pluck="name",
	):
		frappe.delete_doc("File", name, ignore_permissions=True, force=True)
	for name in uploads:
		frappe.db.delete("Email Upload", {"name": name})

	leads = set(frappe.get_all(CONTACT, filters={"source": ["like", f"{DEMO_SOURCE}%"]}, pluck="name"))
	leads.update(frappe.get_all(CONTACT, filters={"domain": ["in", DEMO_DOMAINS]}, pluck="name"))
	for chunk in chunks(sorted(leads)):
		frappe.db.delete(CONTACT, {"name": ["in", chunk]})
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
	return {
		"email_uploads": uploads,
		"users": users,
		"leads_deleted": len(leads),
		"signed_partners_deleted": partners,
	}


def _numbers(rng):
	"""Valid, distinct mobile numbers near each region's documented example number."""
	seen = set()
	while True:
		region = rng.choice(REGIONS)
		example = phonenumbers.example_number_for_type(region, phonenumbers.PhoneNumberType.MOBILE)
		candidate = phonenumbers.PhoneNumber(
			country_code=example.country_code, national_number=example.national_number + rng.randint(1, 999)
		)
		e164 = phonenumbers.format_number(candidate, phonenumbers.PhoneNumberFormat.E164)
		if phonenumbers.is_valid_number(candidate) and e164 not in seen:
			seen.add(e164)
			yield e164, region


def _lead(email, whatsapp, region, organization, status, user, when, rng) -> dict:
	contacted = status != "Claimed"
	return {
		"email": email,
		"domain": email.split("@")[1] if email else None,
		"whatsapp": whatsapp,
		"organization": organization,
		"country": country_name(region),
		"status": status,
		"source": DEMO_SOURCE,
		"uploaded_by": user,
		"email_upload": None,
		"claimed_on": when,
		"last_contacted_on": when + timedelta(hours=rng.randint(1, 48)) if contacted else None,
		"replied_on": when + timedelta(days=rng.randint(1, 5))
		if status in ("Replied", "In Discussion")
		else None,
		"signed_on": when + timedelta(days=rng.randint(5, 20)) if status == "Signed Partner" else None,
		"owner": user,
		"modified_by": user,
		"creation": when,
		"modified": when,
	}


def _make_upload(owner, upload_type, source, created, leads):
	"""A finished upload with a realistic source file and result counts."""
	content = "Company,Email,WhatsApp,Country\n" + "".join(
		f"{lead['organization']},{lead['email']},{lead['whatsapp'] or ''},{lead['country'] or ''}\n"
		for lead in leads
	)
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
			"total_found": len(leads),
			"new_count": len(leads),
		}
	).insert(ignore_permissions=True)
	file_doc.db_set(
		{"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "attached_to_field": "file"}
	)
	frappe.db.set_value(
		doc.doctype,
		doc.name,
		{"owner": owner, "modified_by": owner, "creation": created, "modified": created},
		update_modified=False,
	)
	doc.owner, doc.creation = owner, created
	return doc
