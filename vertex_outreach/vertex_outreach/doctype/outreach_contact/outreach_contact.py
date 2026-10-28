# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, now

from vertex_outreach.contacts import (
	CLAIMED,
	CONTACTED,
	REPLIED,
	SIGNED,
	country_name,
	country_region,
	describe_lead,
	excluded_regions,
	find_leads,
	full_names,
	lead_details,
)
from vertex_outreach.identifiers import LeadInput, email_domain, normalize_email, normalize_phone

STATUS_DATES = {
	CLAIMED: "claimed_on",
	CONTACTED: "last_contacted_on",
	REPLIED: "replied_on",
	"In Discussion": "replied_on",
	SIGNED: "signed_on",
}


class OutreachContact(Document):
	def before_insert(self):
		self.uploaded_by = self.uploaded_by or frappe.session.user

	def validate(self):
		# The same normalization uploads and Check Leads use, so the unique indexes see one form
		self._normalize_identifiers()
		self._check_duplicates()
		if self.is_new() and self.status == CLAIMED:
			self._check_excluded_country()
		if self.is_new() or self.has_value_changed("status"):
			field = STATUS_DATES.get(self.status)
			if field and not self.get(field):
				self.set(field, now())

	def after_insert(self):
		if not self.organization:
			return
		# The column's collation is case-insensitive
		others = frappe.db.count(self.doctype, {"organization": self.organization, "name": ["!=", self.name]})
		if others:
			frappe.msgprint(
				_("1 other lead named {0}").format(escape_html(self.organization))
				if others == 1
				else _("{0} other leads named {1}").format(others, escape_html(self.organization)),
				alert=True,
				indicator="blue",
			)

	def _normalize_identifiers(self):
		self.organization = (self.organization or "").strip() or None
		self._phone_region = None

		if raw := (self.email or "").strip():
			self.email = normalize_email(raw)
			if not self.email:
				frappe.throw(
					_("{0} is not a valid email address").format(escape_html(raw)), title=_("Invalid email")
				)
			self.domain = email_domain(self.email)
		else:
			self.email = self.domain = None

		if raw := (self.whatsapp or "").strip():
			phone = normalize_phone(raw, country_region(self.country))
			if not phone.e164:
				frappe.throw(
					_("{0} is not a valid WhatsApp number: {1}").format(escape_html(raw), _(phone.error)),
					title=_("Invalid WhatsApp number"),
				)
			self.whatsapp, self._phone_region = phone.e164, phone.region
			self.country = self.country or country_name(phone.region)
		else:
			self.whatsapp = None

		if not self.email and not self.whatsapp:
			frappe.throw(_("Enter an email, a WhatsApp number, or both."), title=_("Missing identifier"))

	def _check_duplicates(self):
		by_email, by_whatsapp = find_leads([self.email], [self.whatsapp])
		clashes = [
			(label, value, lead)
			for label, value, lead in (
				(_("email"), self.email, by_email.get(self.email)),
				(_("WhatsApp number"), self.whatsapp, by_whatsapp.get(self.whatsapp)),
			)
			if lead and lead.name != self.name
		]
		if not clashes:
			return

		names = full_names({lead.uploaded_by or lead.owner for _l, _v, lead in clashes})
		lines = [
			_("This {0} ({1}) is already on {2}.").format(
				label, value, describe_lead(lead_details(lead, names))
			)
			for label, value, lead in clashes
		]
		if len({lead.name for _l, _v, lead in clashes}) > 1:
			lines.append(_("They belong to two different leads, so a manager needs to review this conflict."))
		frappe.throw(
			"<br>".join(escape_html(line) for line in lines),
			title=_("Already in the system"),
			exc=frappe.DuplicateEntryError,
		)

	def _check_excluded_country(self):
		lead = LeadInput(
			input="", email=self.email, region=self._phone_region, country=country_region(self.country)
		)
		if excluded := sorted(lead.regions & excluded_regions()):
			frappe.throw(
				_("Leads in {0} cannot be claimed (Outreach Settings > Excluded Countries).").format(
					", ".join(country_name(r) or r for r in excluded)
				),
				title=_("Excluded country"),
			)
