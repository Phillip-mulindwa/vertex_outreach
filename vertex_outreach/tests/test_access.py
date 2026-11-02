# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.desk.desktop import get_workspace_sidebar_items
from frappe.tests.utils import FrappeTestCase

from vertex_outreach import access
from vertex_outreach.api import check_leads, mark_contacted
from vertex_outreach.contacts import ALREADY_CONTACTED, CLAIMED, CONTACT, CONTACTED, FRESH

CHECKER = "checker.one@vertex-vo.example"
OTHER_CHECKER = "checker.two@vertex-vo.example"
MANAGER = "manager.one@vertex-vo.example"


def make_user(email, *roles):
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"roles": [{"role": r} for r in roles],
		}
	)
	user.flags.no_welcome_mail = True
	return user.insert(ignore_permissions=True)


class CheckerTestCase(FrappeTestCase):
	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		make_user(CHECKER, "Outreach User")
		make_user(OTHER_CHECKER, "Outreach User")
		make_user(MANAGER, "Outreach User", "Outreach Manager")

	def lead(self, email, user, status=CLAIMED):
		doc = frappe.get_doc(
			{"doctype": CONTACT, "email": email, "status": status, "uploaded_by": user}
		).insert(ignore_permissions=True)
		doc.db_set("owner", user)
		return doc.name


class TestCheckerRole(CheckerTestCase):
	def test_only_outreach_users_without_a_manager_role_are_checkers(self):
		self.assertTrue(access.is_checker(CHECKER))
		self.assertFalse(access.is_checker(MANAGER))
		self.assertFalse(access.is_checker("Administrator"))

	def test_checker_permissions(self):
		frappe.set_user(CHECKER)
		self.assertTrue(frappe.has_permission(CONTACT, "read"))
		for ptype in ("create", "delete", "export"):
			self.assertFalse(frappe.has_permission(CONTACT, ptype), ptype)
		for doctype in ("Email Upload", "Outreach Settings"):
			self.assertFalse(frappe.has_permission(doctype, "read"), doctype)
		for ptype in ("create", "write"):
			self.assertFalse(frappe.has_permission("Signed Partner", ptype), ptype)
		self.assertFalse(frappe.get_doc("Report", "Outreach Summary").is_permitted())
		self.assertTrue(frappe.get_doc("Page", "check-leads").is_permitted())


class TestCheckerLeads(CheckerTestCase):
	def test_checker_claims_and_sees_who_has_a_lead(self):
		self.lead("taken@acc-vo.example", OTHER_CHECKER)
		frappe.set_user(CHECKER)

		result = check_leads("taken@acc-vo.example\nfresh@acc-vo.example", claim=1)

		taken, fresh = result["results"]
		self.assertEqual((taken["verdict"], taken["contacted_by"]), (ALREADY_CONTACTED, OTHER_CHECKER))
		self.assertTrue(taken["contacted_on"])
		self.assertEqual((fresh["verdict"], fresh["claimed"]), (FRESH, 1))
		self.assertEqual(frappe.db.get_value(CONTACT, result["claimed"][0], "uploaded_by"), CHECKER)

	def test_mark_contacted_only_on_own_leads(self):
		mine = self.lead("mine@acc-vo.example", CHECKER)
		theirs = self.lead("theirs@acc-vo.example", OTHER_CHECKER)
		frappe.set_user(CHECKER)

		mark_contacted([mine])
		self.assertEqual(frappe.db.get_value(CONTACT, mine, "status"), CONTACTED)
		for names in ([theirs], [mine, theirs]):
			with self.assertRaises(frappe.PermissionError):
				mark_contacted(names)
		self.assertEqual(frappe.db.get_value(CONTACT, theirs, "status"), CLAIMED)

		frappe.set_user(MANAGER)
		mark_contacted([theirs])
		self.assertEqual(frappe.db.get_value(CONTACT, theirs, "status"), CONTACTED)

	def test_checker_lists_only_themselves_as_user(self):
		frappe.set_user(CHECKER)
		self.assertEqual(frappe.get_list("User", pluck="name"), [CHECKER])
		frappe.set_user(MANAGER)
		self.assertIn(OTHER_CHECKER, frappe.get_list("User", pluck="name"))


class TestCheckerDesk(CheckerTestCase):
	def test_restricting_standard_workspaces_is_idempotent(self):
		frappe.db.delete("Has Role", {"parenttype": "Workspace", "parent": "Build"})

		self.assertIn("Build", access.restrict_standard_workspaces())
		self.assertEqual(access.restrict_standard_workspaces(), [])
		roles = frappe.get_all(
			"Has Role", filters={"parenttype": "Workspace", "parent": "Build"}, pluck="role"
		)
		self.assertEqual(roles, ["System Manager"])

	def test_sidebar_shows_checkers_only_outreach(self):
		access.restrict_standard_workspaces()
		frappe.set_user(CHECKER)
		self.assertEqual([p.name for p in get_workspace_sidebar_items()["pages"]], ["Outreach"])
		frappe.set_user(MANAGER)
		self.assertEqual(
			[p.name for p in get_workspace_sidebar_items()["pages"]], ["Outreach", "Outreach Admin"]
		)
		frappe.set_user("Administrator")
		names = [p.name for p in get_workspace_sidebar_items()["pages"]]
		self.assertTrue({"Users", "Build", "Outreach", "Outreach Admin"} <= set(names))

	def test_checker_lands_on_check_leads_after_login(self):
		for user, home_page in ((CHECKER, access.CHECK_LEADS_ROUTE), (MANAGER, "/app")):
			frappe.set_user(user)
			with (
				patch.object(frappe, "request", SimpleNamespace(path="/api/method/login")),
				patch.object(frappe.local, "response", frappe._dict(message="Logged In", home_page="/app")),
			):
				access.send_checkers_to_check_leads()
				self.assertEqual(frappe.local.response["home_page"], home_page)

	def test_checker_boot_offers_only_leads_and_check_leads(self):
		def boot():
			return {
				"user": {
					"can_search": [CONTACT, "ToDo", "Email Upload"],
					"can_create": [CONTACT, "ToDo"],
					"can_read": [CONTACT, "Country", "User"],
				},
				"page_info": {"check-leads": {}, "print": {}, "leaderboard": {}},
			}

		frappe.set_user(CHECKER)
		bootinfo = boot()
		access.trim_checker_boot(bootinfo)
		self.assertEqual(bootinfo["user"]["can_search"], [CONTACT])
		self.assertEqual(bootinfo["user"]["can_create"], [])
		self.assertEqual(bootinfo["user"]["can_read"], [CONTACT, "Country"])
		self.assertEqual(sorted(bootinfo["page_info"]), ["check-leads", "print"])

		frappe.set_user(MANAGER)
		bootinfo = boot()
		access.trim_checker_boot(bootinfo)
		self.assertEqual(bootinfo, boot())
