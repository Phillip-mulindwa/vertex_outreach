# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, getdate, today

from vertex_outreach.contacts import (
	CONTACT,
	CONTACTED,
	SIGNED,
	country_name,
	country_region,
	drop_inherited_countries,
	find_leads,
	lead_conflict_message,
	upsert_partner_lead,
)
from vertex_outreach.identifiers import LeadInput, normalize_email, normalize_phone


class SignedPartner(Document):
	def before_insert(self):
		drop_inherited_countries(self)

	def validate(self):
		self._normalize_identifiers()
		self.signed_on = self.signed_on or today()
		self._check_duplicates()
		by_email, by_whatsapp = find_leads([self.email], [self.whatsapp])
		email_lead, whatsapp_lead = by_email.get(self.email), by_whatsapp.get(self.whatsapp)
		if email_lead and whatsapp_lead and email_lead.name != whatsapp_lead.name:
			frappe.throw(
				escape_html(lead_conflict_message(email_lead, whatsapp_lead)),
				title=_("Conflict between two leads"),
			)

	def on_update(self):
		lead = LeadInput(
			input=self.email or self.whatsapp,
			organization=self.organization,
			email=self.email,
			whatsapp=self.whatsapp,
			region=country_region(self.whatsapp_country),
		)
		upsert_partner_lead(lead, user=frappe.session.user, source="Signed Partner")

	def on_trash(self):
		for field in ("email", "whatsapp"):
			if value := self.get(field):
				lead = frappe.db.get_value(CONTACT, {field: value}, ["name", "status"], as_dict=True)
				if lead and lead.status == SIGNED:
					frappe.db.set_value(CONTACT, lead.name, "status", CONTACTED)

	def _normalize_identifiers(self):
		if raw := (self.email or "").strip():
			self.email = normalize_email(raw)
			if not self.email:
				frappe.throw(
					_("{0} is not a valid email address").format(escape_html(raw)), title=_("Invalid email")
				)
		else:
			self.email = None

		if raw := (self.whatsapp or "").strip():
			phone = normalize_phone(raw, country_region(self.whatsapp_country))
			if not phone.e164:
				frappe.throw(
					_("{0} is not a valid WhatsApp number: {1}").format(escape_html(raw), _(phone.error)),
					title=_("Invalid WhatsApp number"),
				)
			self.whatsapp = phone.e164
			self.whatsapp_country = country_name(phone.region) or self.whatsapp_country
		else:
			self.whatsapp = None

		if not self.email and not self.whatsapp:
			frappe.throw(_("Enter an email, a WhatsApp number, or both."), title=_("Missing identifier"))

	def _check_duplicates(self):
		for field, label in (("email", _("email")), ("whatsapp", _("WhatsApp number"))):
			value = self.get(field)
			if not value:
				continue
			other = frappe.db.get_value(
				self.doctype,
				{field: value, "name": ["!=", self.name]},
				["name", "organization", "signed_on"],
				as_dict=True,
			)
			if other:
				frappe.throw(
					_("This {0} ({1}) is already on signed partner {2} ({3}, signed {4}).").format(
						label,
						value,
						other.name,
						escape_html(other.organization or _("no organization")),
						getdate(other.signed_on).strftime("%-d %b %Y"),
					),
					title=_("Already a signed partner"),
					exc=frappe.DuplicateEntryError,
				)
