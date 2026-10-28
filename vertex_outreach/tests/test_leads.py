# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from vertex_outreach import contacts
from vertex_outreach.api import check_leads
from vertex_outreach.contacts import (
	ALREADY_CONTACTED,
	CLAIMED,
	CONFLICT,
	CONTACT,
	CONTACTED,
	EXCLUDED_COUNTRY,
	FRESH,
	claim_fresh,
	classify_rows,
	insert_leads,
	release_stale_claims,
)
from vertex_outreach.identifiers import NEEDS_COUNTRY_CODE, LeadInput, normalize_phone, parse_file, parse_text

UG = "+256772123456"
KE = "+254712123456"
GB = "+447400123456"


class TestIdentifiers(FrappeTestCase):
	def test_number_formats_normalise_to_one_e164(self):
		formats = [
			("+256 772 123456", None),
			("+256-772-123-456", None),
			("(+256) 772 123 456", None),
			("00256772123456", None),
			("00 256 772 123 456", None),
			("https://wa.me/256772123456", None),
			("wa.me/256772123456", None),
			("https://api.whatsapp.com/send?phone=256772123456&text=hi", None),
			("0772 123456", "UG"),
			("(0772) 123-456", "UG"),
			("256772123456", "UG"),
		]
		for raw, default_country in formats:
			with self.subTest(raw=raw):
				phone = normalize_phone(raw, default_country)
				self.assertEqual(phone.e164, UG)
				self.assertEqual(phone.region, "UG")

	def test_number_without_country_code_needs_one(self):
		self.assertEqual(normalize_phone("0772 123456").error, NEEDS_COUNTRY_CODE)
		[item] = parse_text("0772 123456")
		self.assertEqual((item.type, item.error), ("WhatsApp", NEEDS_COUNTRY_CODE))

	def test_line_with_company_email_and_number_is_one_lead(self):
		[item] = parse_text("Acme Ltd, info@acme-vo.example, +254 712 123456")
		self.assertEqual(
			(item.organization, item.email, item.whatsapp, item.region, item.type),
			("Acme Ltd", "info@acme-vo.example", KE, "KE", "Email + WhatsApp"),
		)
		# Two emails on a line cannot be paired with one number: each is its own lead
		items = parse_text("a@vo.example, b@vo.example, +254712123456")
		self.assertEqual([i.type for i in items], ["Email", "Email", "WhatsApp"])

	def test_table_with_header_variants(self):
		csv = (
			"Company Name,E-mail Address,WhatsApp No.,Country\n"
			"Acme,info@acme-vo.example,0712 123456,Kenya\n"
			"Beta,,+44 7400 123456,\n"
		)
		items = parse_file("leads.csv", csv, resolve_country=contacts.country_region)
		self.assertEqual(
			[(i.organization, i.email, i.whatsapp, i.country) for i in items],
			[("Acme", "info@acme-vo.example", KE, "KE"), ("Beta", None, GB, None)],
		)


class LeadTestCase(FrappeTestCase):
	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		settings = frappe.get_single("Outreach Settings")
		settings.release_claimed_after_days = 14
		settings.set("excluded_countries", [{"country": "Uganda"}, {"country": "South Africa"}])
		settings.save(ignore_permissions=True)

	def make_lead(self, **values):
		return frappe.get_doc({"doctype": CONTACT, "status": CONTACTED, **values}).insert(
			ignore_permissions=True
		)

	def classify(self, text, default_country=None):
		items = parse_text(text, default_country)
		return items, classify_rows(items)


class TestMatching(LeadTestCase):
	def test_new_leads_are_named_by_series_not_email(self):
		lead = self.make_lead(email="naming@vo-test.example")
		self.assertTrue(lead.name.startswith("LEAD-"))

	def test_match_by_whatsapp_with_different_email(self):
		lead = self.make_lead(email="old@vo-test.example", whatsapp="+254 712 123456", organization="Acme")
		_items, [info] = self.classify("new.person@vo-test.example +254712123456")
		self.assertEqual(info["verdict"], ALREADY_CONTACTED)
		self.assertEqual(info["matched_on"], "WhatsApp")
		self.assertEqual(info["lead"], lead.name)
		self.assertIn("old@vo-test.example", info["note"])

	def test_same_company_name_with_different_identifiers_stays_fresh(self):
		self.make_lead(email="a@vo-test.example", organization="Vo Test Clinic")
		self.make_lead(whatsapp=GB, organization="  VO TEST clinic ")
		_items, [info] = self.classify("vo test clinic: fresh@vo-test.example")
		self.assertEqual(info["verdict"], FRESH)
		self.assertEqual(info["note"], "2 other leads named Vo Test Clinic")

	def test_conflict(self):
		by_email = self.make_lead(email="one@vo-test.example", organization="One")
		by_whatsapp = self.make_lead(email="two@vo-test.example", whatsapp=KE, organization="Two")
		items, [info] = self.classify(f"one@vo-test.example {KE}")
		self.assertEqual(info["verdict"], CONFLICT)
		self.assertEqual([c["lead"] for c in info["conflict"]], [by_email.name, by_whatsapp.name])
		# never claimable
		self.assertEqual(claim_fresh(items, [info], user="Administrator"), [])

	def test_excluded_country_for_phone_and_email(self):
		_items, infos = self.classify(f"{UG}\nhr@clinic-vo.co.za\n0821234567\nhr@clinic-vo.co.ke", "ZA")
		self.assertEqual(
			[i["verdict"] for i in infos], [EXCLUDED_COUNTRY, EXCLUDED_COUNTRY, EXCLUDED_COUNTRY, FRESH]
		)
		self.assertIn("Uganda", infos[0]["note"])
		self.assertIn("South Africa", infos[1]["note"])

		result = check_leads(f"{UG}\nhr@clinic-vo.co.za", claim=1)
		self.assertEqual(result["claimed"], [])
		self.assertFalse(frappe.db.exists(CONTACT, {"whatsapp": UG}))

		with self.assertRaises(frappe.ValidationError):
			self.make_lead(whatsapp=UG, status=CLAIMED)


class TestClaiming(LeadTestCase):
	def test_check_and_claim_keeps_one_line_on_one_lead(self):
		result = check_leads("Acme Ltd, info@acme-vo.example, +254 712 123456", claim=1)
		[name] = result["claimed"]
		lead = frappe.get_doc(CONTACT, name)
		self.assertEqual(
			(lead.organization, lead.email, lead.whatsapp, lead.country, lead.status),
			("Acme Ltd", "info@acme-vo.example", KE, "Kenya", CLAIMED),
		)
		self.assertTrue(lead.claimed_on)
		self.assertFalse(lead.last_contacted_on)

	def test_only_reports_what_it_inserted(self):
		items, infos = self.classify(f"race@vo-test.example\n{KE}")
		self.assertEqual([i["verdict"] for i in infos], [FRESH, FRESH])
		# someone else claims the number between our check and our insert
		[theirs] = insert_leads(
			[LeadInput(input=KE, email="other@vo-test.example", whatsapp=KE)], CLAIMED, user="Guest"
		)

		claimed = claim_fresh(items, infos, user="Administrator")
		self.assertEqual(len(claimed), 1)
		self.assertEqual(infos[0]["lead"], claimed[0])
		self.assertEqual((infos[1]["verdict"], infos[1]["lead"]), (ALREADY_CONTACTED, theirs))
		self.assertFalse(infos[1].get("claimed"))

	def test_claim_then_release_after_14_days(self):
		[name] = check_leads("stale@vo-test.example", claim=1)["claimed"]
		[contacted] = check_leads("worked@vo-test.example", claim=1)["claimed"]
		contacts.mark_contacted([contacted], last_contacted_on=frappe.utils.now())
		self.assertEqual(frappe.db.get_value(CONTACT, contacted, "status"), CONTACTED)

		with patch("vertex_outreach.contacts.now_datetime", return_value=now_datetime() + timedelta(days=13)):
			release_stale_claims()
		self.assertTrue(frappe.db.exists(CONTACT, name))

		with patch("vertex_outreach.contacts.now_datetime", return_value=now_datetime() + timedelta(days=15)):
			release_stale_claims()
		self.assertFalse(frappe.db.exists(CONTACT, name))
		self.assertTrue(frappe.db.exists(CONTACT, contacted))

		# and it can be claimed fresh
		self.assertEqual(len(check_leads("stale@vo-test.example", claim=1)["claimed"]), 1)

	def test_form_duplicate_message_names_field_owner_and_date(self):
		self.make_lead(email="taken@vo-test.example", organization="Taken Co")
		with self.assertRaises(frappe.DuplicateEntryError) as raised:
			self.make_lead(email="TAKEN@vo-test.example", whatsapp=GB)
		message = str(raised.exception)
		self.assertIn("email (taken@vo-test.example) is already on LEAD-", message)
		self.assertIn("Taken Co", message)
		self.assertIn("Administrator", message)

	def test_lead_needs_an_identifier(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_lead(organization="Nobody")


class TestUploads(LeadTestCase):
	CSV = (
		"Company,Email,WhatsApp,Country\n"
		"Fresh Co,fresh@vo-test.example,,\n"
		"Known Co,new@vo-test.example,+254 712 123456,\n"
		"Conflict Co,one@vo-test.example,+44 7400 123456,\n"
		"Kampala Co,,0772 123456,Uganda\n"
		"Joburg Co,hr@clinic-vo.co.za,,\n"
		"Bad Co,not-an-email,12,\n"
	)

	def setUp(self):
		super().setUp()
		self.make_lead(email="known@vo-test.example", whatsapp=KE)
		self.make_lead(email="one@vo-test.example")
		self.make_lead(email="two@vo-test.example", whatsapp=GB)

	def process(self, upload_type):
		from vertex_outreach.vertex_outreach.doctype.email_upload import email_upload

		doc = frappe.get_doc(
			{
				"doctype": "Email Upload",
				"upload_type": upload_type,
				"file": "/private/files/x.csv",
				"status": "Queued",
			}
		).insert(ignore_permissions=True)
		items = [
			i
			for i in parse_file("leads.csv", self.CSV, resolve_country=contacts.country_region)
			if not i.error
		]
		handler = {
			"Scraped Leads": email_upload._process_scraped_leads,
			"Already Contacted": email_upload._process_already_contacted,
			"Signed Partners": email_upload._process_signed_partners,
		}[upload_type]
		return doc, handler(doc, items)

	def test_scraped_leads_claims_only_fresh_and_leaves_excluded_out_of_clean_file(self):
		_doc, counts = self.process("Scraped Leads")
		self.assertEqual(
			{k: counts[k] for k in ("new_count", "duplicate_count", "conflict_count", "excluded_count")},
			{"new_count": 1, "duplicate_count": 1, "conflict_count": 1, "excluded_count": 2},
		)
		clean = frappe.get_doc("File", {"file_url": counts["clean_file"]}).get_content()
		self.assertIn("fresh@vo-test.example", clean)
		self.assertNotIn("clinic-vo.co.za", clean)
		self.assertNotIn("+256", clean)
		self.assertEqual(frappe.db.get_value(CONTACT, {"email": "fresh@vo-test.example"}, "status"), CLAIMED)
		conflicts = frappe.get_doc("File", {"file_url": counts["conflict_file"]}).get_content()
		self.assertIn("one@vo-test.example", conflicts)

	def test_already_contacted_records_new_leads_as_contacted(self):
		[claimed] = check_leads("claimed@vo-test.example", claim=1)["claimed"]
		self.CSV += "Claimed Co,claimed@vo-test.example,,\n"
		_doc, counts = self.process("Already Contacted")
		self.assertEqual(counts["new_count"], 3)  # fresh, Kampala and Joburg: they were contacted already
		self.assertEqual(
			frappe.db.get_value(CONTACT, {"email": "fresh@vo-test.example"}, "status"), CONTACTED
		)
		self.assertEqual(frappe.db.get_value(CONTACT, claimed, "status"), CONTACTED)

	def test_signed_partners_upgrades_the_lead_matched_by_whatsapp(self):
		_doc, counts = self.process("Signed Partners")
		self.assertEqual(counts["conflict_count"], 1)
		self.assertEqual(frappe.db.get_value(CONTACT, {"whatsapp": KE}, "status"), "Signed Partner")
		self.assertEqual(frappe.db.get_value(CONTACT, {"email": "one@vo-test.example"}, "status"), CONTACTED)


class TestMigratedData(FrappeTestCase):
	"""The 998 emails imported before leads had LEAD- names still match after the migration."""

	UPLOAD = "UPL-00020"

	def test_existing_998_emails_still_match(self):
		if not frappe.db.exists("Email Upload", self.UPLOAD):
			self.skipTest(f"{self.UPLOAD} is only on the vertex.localhost site")

		legacy = frappe.get_all(CONTACT, filters={"email_upload": self.UPLOAD}, fields=["name", "email"])
		self.assertEqual(len(legacy), 998)
		self.assertTrue(all(row.email == row.name for row in legacy))

		file_name = frappe.db.get_value("File", {"attached_to_name": self.UPLOAD}, "name")
		file_doc = frappe.get_doc("File", file_name)
		items = parse_file(file_doc.file_name, file_doc.get_content())
		self.assertEqual(len(items), 998)

		infos = classify_rows(items)
		self.assertEqual({i["verdict"] for i in infos}, {ALREADY_CONTACTED})
		self.assertEqual({i["matched_on"] for i in infos}, {"Email"})
		self.assertEqual({i["lead"] for i in infos}, {row.name for row in legacy})
