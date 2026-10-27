# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from vertex_outreach.contacts import classify_emails, describe_existing, partner_domains
from vertex_outreach.emails import email_domain, normalize_email


class OutreachContact(Document):
	def before_insert(self):
		# Runs before naming, so the primary key is always the normalized address -
		# the same normalization uploads and the email check use.
		email = normalize_email(self.email or "")
		if not email:
			frappe.throw(_("{0} is not a valid email address").format(self.email), title=_("Invalid email"))
		self.email = email
		self.domain = email_domain(email)
		self.uploaded_by = self.uploaded_by or frappe.session.user

		if frappe.db.exists(self.doctype, email):
			info = classify_emails([email])[email]
			frappe.throw(
				f"{email}: {describe_existing(info)}",
				title=_("Already in the system"),
				exc=frappe.DuplicateEntryError,
			)

		if self.status != "Signed Partner" and partner_domains([self.domain]):
			frappe.throw(_("Signed partner: {0}").format(self.domain), title=_("Signed partner"))
