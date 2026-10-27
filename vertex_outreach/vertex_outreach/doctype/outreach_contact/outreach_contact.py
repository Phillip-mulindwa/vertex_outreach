# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from vertex_outreach.emails import email_domain, normalize_email


class OutreachContact(Document):
	def before_insert(self):
		# Runs before naming, so the primary key is always the normalized address.
		email = normalize_email(self.email or "")
		if not email:
			frappe.throw(_("{0} is not a valid email address").format(self.email))
		self.email = email
		self.domain = email_domain(email)
