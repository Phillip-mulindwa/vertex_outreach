# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe

from vertex_outreach.contacts import CONTACT, SIGNED_PARTNER_DOCTYPE
from vertex_outreach.identifiers import normalize_email, normalize_phone


def execute():
	"""Blank identifiers become NULL and stored ones get the canonical form lookups compare with.

	Lookups match the normalized input against the stored value exactly, so '' must be NULL (a
	blank never identifies anyone) and a value saved outside the normalizer ('John.Doe@Gmail.com',
	'+256 772 123456') would never be found. Idempotent: values already canonical are untouched,
	and a value that doesn't normalize, or whose canonical form another row already holds, is
	left as it is and reported.
	"""
	for doctype in (CONTACT, SIGNED_PARTNER_DOCTYPE):
		for field in ("email", "whatsapp"):
			frappe.db.sql(f"UPDATE `tab{doctype}` SET `{field}` = NULL WHERE TRIM(`{field}`) = ''")
		_canonicalize(doctype, "email", normalize_email)
		_canonicalize(doctype, "whatsapp", lambda value: normalize_phone(value).e164)

	frappe.db.sql(
		f"UPDATE `tab{CONTACT}` SET `domain` = SUBSTRING_INDEX(`email`, '@', -1) "
		"WHERE `email` IS NOT NULL AND NOT (`domain` <=> SUBSTRING_INDEX(`email`, '@', -1))"
	)
	frappe.db.sql(f"UPDATE `tab{CONTACT}` SET `domain` = NULL WHERE `email` IS NULL AND `domain` IS NOT NULL")


def _canonicalize(doctype: str, field: str, normalize):
	changed, kept = 0, []
	for name, value in frappe.db.sql(
		f"SELECT `name`, `{field}` FROM `tab{doctype}` WHERE `{field}` IS NOT NULL", as_list=True
	):
		canonical = normalize(value)
		if canonical == value:
			continue
		if not canonical or frappe.db.exists(doctype, {field: canonical, "name": ["!=", name]}):
			kept.append(f"{name}: {value!r}")
			continue
		frappe.db.set_value(doctype, name, field, canonical, update_modified=False)
		changed += 1
	if changed or kept:
		print(f"normalize_lead_identifiers: {doctype}.{field}: {changed} normalized, {len(kept)} left as is")
		for line in kept[:50]:
			print(f"  left as is: {line}")
