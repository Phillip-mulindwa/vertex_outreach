# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import json
import random
import shutil
import subprocess
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from vertex_outreach import contacts
from vertex_outreach.api import check_leads, check_one, validate_whatsapp
from vertex_outreach.contacts import (
	ALREADY_CONTACTED,
	CLAIMED,
	CONFLICT,
	CONTACT,
	CONTACTED,
	DO_NOT_CONTACT,
	EXCLUDED_COUNTRY,
	FRESH,
	SIGNED,
	SIGNED_PARTNER,
	claim_fresh,
	classify_rows,
	insert_leads,
	release_stale_claims,
)
from vertex_outreach.identifiers import NEEDS_COUNTRY_CODE, LeadInput, normalize_phone, parse_file, parse_text
from vertex_outreach.vertex_outreach.doctype.email_upload import email_upload
from vertex_outreach.vertex_outreach.doctype.email_upload.email_upload import (
	NEW_LEADS,
	OLD_UPLOAD_TYPES,
	PAST_CONTACTS,
	SIGNED_PARTNERS,
	UPLOAD_TYPES,
)

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
		return doc, email_upload.HANDLERS[upload_type](doc, items)

	def test_new_leads_claims_only_fresh_and_leaves_excluded_out_of_clean_file(self):
		_doc, counts = self.process(NEW_LEADS)
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

	def test_past_contacts_records_new_leads_as_contacted(self):
		[claimed] = check_leads("claimed@vo-test.example", claim=1)["claimed"]
		self.CSV += "Claimed Co,claimed@vo-test.example,,\n"
		_doc, counts = self.process(PAST_CONTACTS)
		self.assertEqual(counts["new_count"], 3)  # fresh, Kampala and Joburg: they were contacted already
		self.assertEqual(
			frappe.db.get_value(CONTACT, {"email": "fresh@vo-test.example"}, "status"), CONTACTED
		)
		self.assertEqual(frappe.db.get_value(CONTACT, claimed, "status"), CONTACTED)

	def test_signed_partners_upgrades_the_lead_matched_by_whatsapp(self):
		_doc, counts = self.process(SIGNED_PARTNERS)
		self.assertEqual(counts["conflict_count"], 1)
		self.assertEqual(frappe.db.get_value(CONTACT, {"whatsapp": KE}, "status"), SIGNED)
		self.assertEqual(frappe.db.get_value(CONTACT, {"email": "one@vo-test.example"}, "status"), CONTACTED)
		# The WhatsApp-only row (Kampala) gets a Signed Partner record too
		record = frappe.db.get_value(
			"Signed Partner",
			{"whatsapp": UG},
			["name", "email", "whatsapp_country", "organization"],
			as_dict=True,
		)
		self.assertTrue(record.name.startswith("SP-"))
		self.assertEqual(
			(record.email, record.whatsapp_country, record.organization), (None, "Uganda", "Kampala Co")
		)


class TestUploadTypes(LeadTestCase):
	def test_renamed_upload_types(self):
		self.assertEqual(UPLOAD_TYPES, ("New leads to check", "Past contacts (history)", "Signed partners"))
		options = frappe.get_meta("Email Upload").get_field("upload_type").options.split("\n")
		self.assertEqual(tuple(options), UPLOAD_TYPES)
		self.assertEqual(set(email_upload.HANDLERS), set(UPLOAD_TYPES))
		self.assertEqual(frappe.get_meta("Email Upload").get_field("upload_type").default, NEW_LEADS)

	def test_migration_renames_stored_upload_types(self):
		from vertex_outreach.patches.v1_2 import rename_upload_types

		names = []
		for old in OLD_UPLOAD_TYPES:
			doc = frappe.get_doc(
				{
					"doctype": "Email Upload",
					"upload_type": NEW_LEADS,
					"file": "/private/files/x.csv",
					"status": "Done",
				}
			).insert(ignore_permissions=True)
			frappe.db.set_value("Email Upload", doc.name, "upload_type", old)
			names.append(doc.name)
		rename_upload_types.execute()
		self.assertEqual(
			[frappe.db.get_value("Email Upload", n, "upload_type") for n in names],
			list(OLD_UPLOAD_TYPES.values()),
		)
		# compared in Python: the column's collation thinks "Signed Partners" == "Signed partners"
		stored = set(frappe.get_all("Email Upload", pluck="upload_type"))
		self.assertFalse(stored & set(OLD_UPLOAD_TYPES))

	def test_upload_label_is_translated(self):
		frappe.local.lang = "en"
		self.assertEqual(frappe._("Email Upload"), "Upload a list")
		self.assertEqual(frappe._("Outreach Contact"), "Outreach Lead")


class TestSignedPartner(LeadTestCase):
	def make_partner(self, **values):
		return frappe.get_doc({"doctype": "Signed Partner", "organization": "Partner Co", **values}).insert(
			ignore_permissions=True
		)

	def test_whatsapp_only_signed_partner(self):
		partner = self.make_partner(whatsapp_country="Kenya", whatsapp="0712 123 456")
		self.assertTrue(partner.name.startswith("SP-"))
		self.assertEqual((partner.whatsapp, partner.email, partner.whatsapp_country), (KE, None, "Kenya"))

		lead = frappe.get_doc(CONTACT, {"whatsapp": KE})
		self.assertEqual((lead.status, lead.organization, lead.email), (SIGNED, "Partner Co", None))
		self.assertEqual(check_one(whatsapp=KE)["verdict"], SIGNED_PARTNER)

		with self.assertRaises(frappe.DuplicateEntryError):
			self.make_partner(whatsapp=KE)

		partner.delete()
		self.assertEqual(frappe.db.get_value(CONTACT, lead.name, "status"), CONTACTED)

	def test_needs_email_or_whatsapp(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_partner()

	def test_fills_the_matched_lead(self):
		lead = self.make_lead(whatsapp=KE, organization="Old Name")
		self.make_partner(email="Boss@Partner-VO.example", whatsapp=KE, organization="Partner Co")
		lead.reload()
		self.assertEqual(
			(lead.status, lead.email, lead.whatsapp, lead.organization),
			(SIGNED, "boss@partner-vo.example", KE, "Partner Co"),
		)

	def test_identifier_already_different_on_the_lead_gets_its_own_lead(self):
		lead = self.make_lead(email="old@partner-vo.example", whatsapp=KE)
		self.make_partner(email="new@partner-vo.example", whatsapp=KE)
		self.assertEqual(
			frappe.db.get_value(CONTACT, lead.name, ["status", "email"]), (SIGNED, "old@partner-vo.example")
		)
		self.assertEqual(frappe.db.get_value(CONTACT, {"email": "new@partner-vo.example"}, "status"), SIGNED)

	def test_conflict_blocks_the_save(self):
		self.make_lead(email="one@partner-vo.example", organization="One")
		self.make_lead(whatsapp=KE, organization="Two")
		with self.assertRaises(frappe.ValidationError) as raised:
			self.make_partner(email="one@partner-vo.example", whatsapp=KE)
		self.assertIn("A manager needs to review this conflict", str(raised.exception))
		self.assertFalse(frappe.db.exists("Signed Partner", {"email": "one@partner-vo.example"}))


class TestCheckOne(LeadTestCase):
	def test_fresh_then_claim_creates_one_lead(self):
		self.make_lead(email="someone@vo-test.example", organization="Vo Single Co")
		result = check_one(company="Vo Single Co", email="hello@vo-single.example", whatsapp="+254712123456")
		self.assertEqual((result["verdict"], result["summary"]), (FRESH, "FRESH: no match"))
		self.assertEqual(result["note"], "1 other lead named Vo Single Co")
		self.assertIsNone(result["claimed"])

		result = check_one(
			company="Vo Single Co",
			email="hello@vo-single.example",
			whatsapp="0712 123456",
			whatsapp_country="Kenya",
			claim=1,
		)
		lead = frappe.get_doc(CONTACT, result["claimed"])
		self.assertEqual(
			(lead.organization, lead.email, lead.whatsapp, lead.whatsapp_country, lead.status),
			("Vo Single Co", "hello@vo-single.example", KE, "Kenya", CLAIMED),
		)
		self.assertIn(lead.name, result["summary"])

	def test_already_contacted(self):
		lead = self.make_lead(email="old@vo-test.example", whatsapp=KE, organization="Acme Travel")
		result = check_one(email="other@vo-test.example", whatsapp="+254 712 123 456")
		self.assertEqual(result["verdict"], ALREADY_CONTACTED)
		self.assertRegex(
			result["summary"],
			rf"^ALREADY CONTACTED — Matched on WhatsApp: \+254712123456 → {lead.name} \(Acme Travel\), "
			r"contacted by Administrator on \d+ \w+ \d{4}$",
		)
		self.assertEqual(result["note"], "The lead has a different email: old@vo-test.example")

	def test_signed_partner(self):
		self.make_lead(email="partner@vo-test.example", status=SIGNED)
		result = check_one(email="partner@vo-test.example")
		self.assertEqual(result["verdict"], SIGNED_PARTNER)
		self.assertTrue(
			result["summary"].startswith(
				"SIGNED PARTNER — Matched on Email: partner@vo-test.example → LEAD-"
			),
			result["summary"],
		)

	def test_do_not_contact(self):
		self.make_lead(email="gone@vo-test.example", status="Unsubscribed")
		self.assertEqual(check_one(email="gone@vo-test.example")["verdict"], DO_NOT_CONTACT)

	def test_conflict(self):
		self.make_lead(email="one@vo-test.example")
		self.make_lead(whatsapp=KE)
		result = check_one(email="one@vo-test.example", whatsapp=KE, claim=1)
		self.assertEqual(result["verdict"], CONFLICT)
		self.assertIsNone(result["claimed"])
		self.assertRegex(
			result["summary"],
			r"^CONFLICT — Matched on Email: one@vo-test.example → LEAD-\d+, contacted by .*; "
			rf"Matched on WhatsApp: \{KE} → LEAD-\d+",
		)

	def test_excluded_country(self):
		result = check_one(whatsapp="0772 123456", whatsapp_country="Uganda", claim=1)
		self.assertEqual(result["verdict"], EXCLUDED_COUNTRY)
		self.assertIsNone(result["claimed"])
		self.assertIn("Uganda", result["summary"])

	def test_invalid_input_is_refused_with_a_friendly_message(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Add the country code"):
			check_one(whatsapp="0772 123456")
		with self.assertRaisesRegex(frappe.ValidationError, "doesn't look right"):
			check_one(email="name@company")
		with self.assertRaisesRegex(frappe.ValidationError, "Enter an email or a WhatsApp number"):
			check_one(company="Only a name")
		self.assertEqual(validate_whatsapp("0772 123456", "Uganda"), {"whatsapp": UG, "country": "Uganda"})
		self.assertIn("Add the country code", validate_whatsapp("0772 123456")["error"])


class TestInheritedCountry(LeadTestCase):
	"""frappe.new_doc (Data Import) fills a lead's country with the system country."""

	ZA = "+27821234567"

	def setUp(self):
		super().setUp()
		self.system_country = frappe.db.get_default("country")
		if not self.system_country:
			self.skipTest("no system country set")

	def new_lead(self, **values):
		doc = frappe.new_doc(CONTACT)
		doc.update({"status": CONTACTED, **values})
		return doc.insert(ignore_permissions=True)

	def test_new_doc_lead_does_not_keep_the_system_country(self):
		self.assertEqual(frappe.new_doc(CONTACT).country, self.system_country)
		self.assertIsNone(self.new_lead(email="inherit@country-vo.example").country)
		self.assertEqual(self.new_lead(whatsapp=KE).country, "Kenya")
		self.assertEqual(self.new_lead(email="kenya@country-vo.example", country="Kenya").country, "Kenya")

	def test_whatsapp_number_backs_the_country(self):
		lead = self.new_lead(whatsapp=self.ZA, country="South Africa")
		self.assertEqual((lead.country, lead.whatsapp_country), ("South Africa", "South Africa"))

	def test_partner_and_upload_country_fields(self):
		inherited = frappe._dict(
			country=self.system_country,
			whatsapp_country=self.system_country,
			default_country=self.system_country,
		)
		with patch.object(contacts, "get_new_doc", return_value=inherited):
			partner = frappe.new_doc("Signed Partner")
			partner.update(
				{
					"organization": "Country Co",
					"email": "partner@country-vo.example",
					"whatsapp_country": self.system_country,
				}
			)
			partner.insert(ignore_permissions=True)
			self.assertIsNone(partner.whatsapp_country)

			upload = frappe.new_doc("Email Upload")
			upload.default_country = self.system_country
			contacts.drop_inherited_countries(upload)
			self.assertIsNone(upload.default_country)

	def test_patch_clears_only_unbacked_default_country(self):
		from vertex_outreach.patches.v1_2 import clear_default_lead_country

		plain = self.make_lead(email="plain@country-vo.example")
		backed = self.make_lead(whatsapp=self.ZA)
		other = self.make_lead(whatsapp=KE)
		for lead in (plain, backed, other):
			lead.db_set("country", self.system_country)

		clear_default_lead_country.execute()
		self.assertIsNone(frappe.db.get_value(CONTACT, plain.name, "country"))
		self.assertEqual(frappe.db.get_value(CONTACT, backed.name, "country"), self.system_country)
		self.assertIsNone(frappe.db.get_value(CONTACT, other.name, "country"))


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


class TestDeskAssets(FrappeTestCase):
	def test_shared_desk_js_is_a_bundle(self):
		"""A plain /assets/... path is cached by browsers for 12h with no version in the URL, so a stale
		copy without newer helpers (make_single_check) broke Check Leads. Bundles get a hashed name."""
		import os

		from vertex_outreach import hooks

		includes = hooks.app_include_js if isinstance(hooks.app_include_js, list) else [hooks.app_include_js]
		for include in includes:
			self.assertTrue(include.endswith(".bundle.js"), include)
			self.assertTrue(os.path.exists(frappe.get_app_path("vertex_outreach", "public", "js", include)))
		with open(frappe.get_app_path("vertex_outreach", "public", "js", "check_leads.js")) as f:
			self.assertIn("vertex_outreach.make_single_check = function", f.read())


class TestStrictMatching(LeadTestCase):
	"""The verdict comes only from an Outreach Lead whose email or WhatsApp number equals the
	normalized input. Blanks, junk, company names and unpicked countries never match."""

	COUNT = 200

	def setUp(self):
		super().setUp()
		self.random = random.Random(20261102)
		# Leads with one identifier missing, as NULL and as '' (written around the controller,
		# as old imports or direct SQL could have), plus a WhatsApp-only Signed Partner
		self.make_lead(email="email-only@vo-strict.example", organization="Acme Travel")
		self.make_lead(whatsapp=KE, organization="Number Only Co")
		blank_whatsapp = self.make_lead(email="blank-whatsapp@vo-strict.example")
		blank_email = self.make_lead(whatsapp=GB)
		frappe.db.sql(f"UPDATE `tab{CONTACT}` SET `whatsapp` = '' WHERE `name` = %s", blank_whatsapp.name)
		frappe.db.sql(f"UPDATE `tab{CONTACT}` SET `email` = '' WHERE `name` = %s", blank_email.name)
		frappe.get_doc(
			{"doctype": "Signed Partner", "organization": "Partner Co", "whatsapp": "+447400654321"}
		).insert(ignore_permissions=True)

	def new_emails(self):
		domains = ["vo-strict.example", "gmail.com", "company-vo.com", "mail-vo.co.ke"]
		emails = [f"{uuid.uuid4().hex[:12]}@{self.random.choice(domains)}" for _i in range(self.COUNT)]
		self.assertFalse(frappe.get_all(CONTACT, filters={"email": ["in", emails]}))
		return emails

	def new_numbers(self):
		numbers = set()
		while len(numbers) < self.COUNT:
			prefix, digits = self.random.choice([("+2547", 8), ("+447", 9)])
			number = prefix + "".join(self.random.choices("0123456789", k=digits))
			if normalize_phone(number).e164 == number:
				numbers.add(number)
		numbers = sorted(numbers)
		self.assertFalse(frappe.get_all(CONTACT, filters={"whatsapp": ["in", numbers]}))
		return numbers

	def assert_all_fresh(self, results):
		self.assertEqual(
			[(r.get("input"), r["verdict"]) for r in results if r["verdict"] != FRESH], [], "not FRESH"
		)
		self.assertEqual(len(results), self.COUNT)

	def test_new_emails_without_whatsapp_are_fresh(self):
		emails = self.new_emails()
		self.assert_all_fresh([check_one(email=e, whatsapp="", whatsapp_country="") for e in emails])
		self.assert_all_fresh(check_leads("\n".join(emails))["results"])

	def test_new_emails_with_new_numbers_are_fresh(self):
		pairs = list(zip(self.new_emails(), self.new_numbers(), strict=True))
		self.assert_all_fresh([check_one(email=e, whatsapp=w) for e, w in pairs])
		self.assert_all_fresh(check_leads("\n".join(f"{e} {w}" for e, w in pairs))["results"])

	def test_blank_identifiers_never_match(self):
		for email, whatsapp in (("brand-new@vo-strict.example", ""), ("", "+254733111222")):
			with self.subTest(email=email, whatsapp=whatsapp):
				self.assertEqual(check_one(email=email, whatsapp=whatsapp)["verdict"], FRESH)
		# '' or whitespace on the input side never looks anything up either
		for blank in ("", " ", None):
			items = [
				LeadInput(input="x", email="brand-new@vo-strict.example", whatsapp=blank),
				LeadInput(input="y", email=blank, whatsapp="+254733111222"),
			]
			self.assertEqual([i["verdict"] for i in classify_rows(items)], [FRESH, FRESH])
		self.assertEqual(contacts.find_leads(["", None, " "], ["", None, " "]), ({}, {}))

	def test_new_email_with_existing_whatsapp_matches_on_whatsapp(self):
		lead = frappe.get_doc(CONTACT, {"whatsapp": KE})
		result = check_one(email="brand-new@vo-strict.example", whatsapp="+254 712 123 456")
		self.assertEqual(
			(result["verdict"], result["matched_on"], result["lead"]),
			(ALREADY_CONTACTED, "WhatsApp", lead.name),
		)
		self.assertTrue(
			result["proof_text"].startswith(
				f"Matched on WhatsApp: {KE} → {lead.name} (Number Only Co), contacted by"
			),
			result["proof_text"],
		)

	def test_existing_email_in_another_case_or_with_gmail_dots_matches_on_email(self):
		gmail = self.make_lead(email="john.doe@gmail.com", organization="Doe Ltd")
		self.assertEqual(gmail.email, "johndoe@gmail.com")
		for typed, lead_name, stored in (
			("J.O.H.N.D.O.E+promo@GoogleMail.com", gmail.name, "johndoe@gmail.com"),
			("  John.Doe@Gmail.com ", gmail.name, "johndoe@gmail.com"),
			("EMAIL-ONLY@VO-STRICT.example", None, "email-only@vo-strict.example"),
		):
			with self.subTest(typed=typed):
				result = check_one(email=typed)
				self.assertEqual((result["verdict"], result["matched_on"]), (ALREADY_CONTACTED, "Email"))
				if lead_name:
					self.assertEqual(result["lead"], lead_name)
				self.assertIn(f"Matched on Email: {stored} → LEAD-", result["proof_text"])

	def test_junk_whatsapp_is_left_out_not_matched(self):
		for junk in ("abc", "12", "+1 23", "call me", "n/a", "0", "Acme Travel"):
			with self.subTest(junk=junk):
				result = check_one(email="brand-new@vo-strict.example", whatsapp=junk)
				self.assertEqual((result["verdict"], result["whatsapp"]), (FRESH, None))
				self.assertIn(f"WhatsApp {junk} was not checked", result["note"])
		self.assertEqual(
			[r["verdict"] for r in check_leads("brand-new@vo-strict.example abc 12")["results"]], [FRESH]
		)

	def test_no_country_is_assumed_for_a_number_without_one(self):
		# +254712123456 is on a lead, but "0712 123456" is only Kenyan when Kenya is picked
		result = check_one(email="brand-new@vo-strict.example", whatsapp="0712 123456")
		self.assertEqual((result["verdict"], result["whatsapp"]), (FRESH, None))
		self.assertIn("Add the country code", result["note"])
		self.assertEqual(
			check_one(whatsapp="0712 123456", whatsapp_country="Kenya")["verdict"], ALREADY_CONTACTED
		)
		self.assertEqual(
			[r["verdict"] for r in check_leads("brand-new@vo-strict.example 0712 123456")["results"]],
			[FRESH, "INVALID"],
		)
		frappe.defaults.set_user_default("outreach_default_country", "Kenya")
		self.assertEqual(check_one(whatsapp="+254 733 111 222", whatsapp_country="")["verdict"], FRESH)
		self.assertFalse(check_leads("0712 123456")["results"][0].get("lead"))

	def test_company_name_is_only_a_note(self):
		result = check_one(company="Acme Travel", email="brand-new@vo-strict.example")
		self.assertEqual((result["verdict"], result["note"]), (FRESH, "1 other lead named Acme Travel"))
		self.assertFalse(result.get("lead"))

	def test_signed_partner_and_do_not_contact_show_their_proof(self):
		partner = frappe.get_doc(CONTACT, {"whatsapp": "+447400654321"})
		result = check_one(whatsapp="+44 7400 654321")
		self.assertEqual(result["verdict"], SIGNED_PARTNER)
		self.assertTrue(
			result["proof_text"].startswith(
				f"Matched on WhatsApp: +447400654321 → {partner.name} (Partner Co)"
			)
		)
		self.make_lead(email="gone@vo-strict.example", status="Bounced")
		result = check_one(email="gone@vo-strict.example")
		self.assertEqual(result["verdict"], DO_NOT_CONTACT)
		self.assertIn("Matched on Email: gone@vo-strict.example → LEAD-", result["summary"])

	def test_proof_names_who_claimed_and_when(self):
		from vertex_outreach.tests.test_access import make_user

		make_user("damalie@vo-strict.example", "Outreach User")
		frappe.db.set_value("User", "damalie@vo-strict.example", "full_name", "Damalie")
		lead = self.make_lead(
			email="claimed@vo-strict.example",
			organization="Acme",
			status=CLAIMED,
			uploaded_by="damalie@vo-strict.example",
		)
		day = frappe.utils.getdate(lead.claimed_on).strftime("%-d %b %Y")
		[row] = check_leads("claimed@vo-strict.example")["results"]
		self.assertEqual(
			row["proof_text"],
			f"Matched on Email: claimed@vo-strict.example → {lead.name} (Acme), claimed by Damalie on {day}",
		)
		self.assertEqual(
			row["proof"],
			[
				{
					"matched_on": [["Email", "claimed@vo-strict.example"]],
					"lead": lead.name,
					"details": f" (Acme), claimed by Damalie on {day}",
				}
			],
		)


class TestCheckLeadsPayload(LeadTestCase):
	"""Replays the payloads public/js/check_leads.js sends (captured by tests/js/single_check.test.js)
	through the whitelisted API, as a checker."""

	def setUp(self):
		super().setUp()
		node = shutil.which("node")
		if not node:
			self.skipTest("node is not installed")
		script = frappe.get_app_path("vertex_outreach", "tests", "js", "single_check.test.js")
		run = subprocess.run([node, script], capture_output=True, text=True, timeout=60)
		self.assertEqual(run.returncode, 0, run.stderr)
		self.payloads = json.loads(run.stdout)

		from vertex_outreach.tests.test_access import CHECKER, make_user

		make_user(CHECKER, "Outreach User")
		existing = self.payloads["existing"]
		self.lead = self.make_lead(
			email=existing["email"], whatsapp=existing["whatsapp"], organization="Old Co"
		)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(CHECKER)

	def post(self, method, payload):
		"""What /api/method/<method> does with the form the desk posts (every value a string)."""
		from frappe.handler import execute_cmd

		form = frappe._dict({k: str(v) for k, v in payload.items()})
		with (
			patch.object(frappe.local, "form_dict", form),
			patch.object(frappe.local, "request", SimpleNamespace(method="POST"), create=True),
		):
			return execute_cmd(method)

	def test_single_check_payloads(self):
		existing = self.post("vertex_outreach.api.check_one", self.payloads["existing"])
		self.assertEqual(
			(existing["verdict"], existing["matched_on"], existing["lead"]),
			(ALREADY_CONTACTED, "Email + WhatsApp", self.lead.name),
		)
		self.assertTrue(
			existing["summary"].startswith(
				f"ALREADY CONTACTED — Matched on Email: {self.lead.email} + WhatsApp: {KE} → {self.lead.name} (Old Co)"
			),
			existing["summary"],
		)

		fresh = self.post("vertex_outreach.api.check_one", self.payloads["fresh"])
		self.assertEqual((fresh["verdict"], fresh["summary"]), (FRESH, "FRESH: no match"))
		self.assertEqual(
			fresh["checked"], {"company": None, "email": self.payloads["fresh"]["email"], "whatsapp": None}
		)

	def test_check_many_payload(self):
		result = self.post("vertex_outreach.api.check_leads", self.payloads["many"])
		self.assertEqual([r["verdict"] for r in result["results"]], [FRESH])


class TestNormalizeIdentifiersPatch(LeadTestCase):
	def test_blanks_become_null_and_values_canonical_idempotently(self):
		from vertex_outreach.patches.v1_4 import normalize_lead_identifiers

		blank = self.make_lead(email="blank-patch@vo-strict.example")
		messy = self.make_lead(email="messy-patch@vo-strict.example")
		taken = self.make_lead(email="taken.patch@gmail.com")
		clash = self.make_lead(email="clash-patch@vo-strict.example")
		set_raw = "UPDATE `tabOutreach Contact` SET `email` = %s, `whatsapp` = %s WHERE `name` = %s"
		frappe.db.sql(set_raw, ("blank-patch@vo-strict.example", "  ", blank.name))
		frappe.db.sql(set_raw, ("Messy.Patch+x@GoogleMail.com", "+254 712 123 456", messy.name))
		frappe.db.sql(set_raw, ("Taken.Patch@gmail.com", None, clash.name))

		for _run in range(2):
			normalize_lead_identifiers.execute()
			self.assertIsNone(frappe.db.get_value(CONTACT, blank.name, "whatsapp"))
			self.assertEqual(
				frappe.db.get_value(CONTACT, messy.name, ["email", "domain", "whatsapp"]),
				("messypatch@gmail.com", "gmail.com", KE),
			)
			# its canonical form is on another lead: left for a manager, not merged or lost
			self.assertEqual(frappe.db.get_value(CONTACT, clash.name, "email"), "Taken.Patch@gmail.com")
			self.assertEqual(frappe.db.get_value(CONTACT, taken.name, "email"), "takenpatch@gmail.com")
		self.assertEqual(check_one(email="messy.patch@gmail.com")["lead"], messy.name)
