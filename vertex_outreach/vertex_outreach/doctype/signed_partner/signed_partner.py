# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from vertex_outreach.contacts import CONTACT, CONTACTED, SIGNED, mark_leads_signed
from vertex_outreach.identifiers import LeadInput, normalize_email


class SignedPartner(Document):
	def before_naming(self):
		# Naming runs before validate; normalize first so the record ID is the canonical email
		self._normalize_email()

	def validate(self):
		self._normalize_email()
		self.signed_on = self.signed_on or today()
		if self.is_new() and frappe.db.exists(self.doctype, self.email):
			existing = frappe.db.get_value(
				self.doctype, self.email, ["organization", "signed_on"], as_dict=True
			)
			frappe.throw(
				_("{0} is already a signed partner ({1}, signed {2}).").format(
					self.email,
					existing.organization or _("no organization"),
					getdate(existing.signed_on).strftime("%-d %b %Y"),
				),
				title=_("Already a signed partner"),
				exc=frappe.DuplicateEntryError,
			)

	def on_update(self):
		lead = LeadInput(input=self.email, email=self.email, organization=self.organization)
		mark_leads_signed([lead], user=frappe.session.user, source="Signed Partner")

	def on_trash(self):
		lead = frappe.db.get_value(CONTACT, {"email": self.email}, ["name", "status"], as_dict=True)
		if lead and lead.status == SIGNED:
			frappe.db.set_value(CONTACT, lead.name, "status", CONTACTED)

	def _normalize_email(self):
		email = normalize_email(self.email or "")
		if not email:
			frappe.throw(_("{0} is not a valid email address").format(self.email), title=_("Invalid email"))
		self.email = email
