# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from vertex_outreach.contacts import CONTACT, mark_contacts_signed
from vertex_outreach.emails import normalize_email


class SignedPartner(Document):
	def before_naming(self):
		# Naming runs before validate; normalize first so the record ID is the canonical email
		self._normalize_email()

	def validate(self):
		self._normalize_email()
		self.signed_on = self.signed_on or today()
		if self.is_new() and frappe.db.exists(self.doctype, self.email):
			existing = frappe.db.get_value(self.doctype, self.email, ["organization", "signed_on"], as_dict=True)
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
		mark_contacts_signed({self.email: self.organization}, user=frappe.session.user, source="Signed Partner")

	def on_trash(self):
		if frappe.db.get_value(CONTACT, self.email, "status") == "Signed Partner":
			frappe.db.set_value(CONTACT, self.email, "status", "Contacted")

	def _normalize_email(self):
		email = normalize_email(self.email or "")
		if not email:
			frappe.throw(_("{0} is not a valid email address").format(self.email), title=_("Invalid email"))
		self.email = email
