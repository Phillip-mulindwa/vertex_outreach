# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

"""Leads claimed, contacted, replied and signed per user, by default over the last 7 days.

Each lead is credited to the user who claimed or uploaded it, on the date of each step.
"""

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, getdate, today

from vertex_outreach.contacts import CONTACT

STEPS = (
	("claimed", "Claimed", "claimed_on"),
	("contacted", "Contacted", "last_contacted_on"),
	("replied", "Replied", "replied_on"),
	("signed", "Signed", "signed_on"),
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.to_date or today())
	from_date = getdate(filters.from_date or add_days(to_date, -7))
	start, end = get_datetime(f"{from_date} 00:00:00"), get_datetime(f"{to_date} 23:59:59.999999")

	counts: dict[str, dict] = {}
	for key, _label, field in STEPS:
		for user, count in frappe.db.sql(
			f"SELECT COALESCE(`uploaded_by`, `owner`), COUNT(*) FROM `tab{CONTACT}` "
			f"WHERE `{field}` BETWEEN %s AND %s GROUP BY 1",
			(start, end),
		):
			counts.setdefault(user, {"user": user})[key] = count

	columns = [
		{"fieldname": "user", "label": _("User"), "fieldtype": "Link", "options": "User", "width": 240}
	]
	columns += [
		{"fieldname": key, "label": _(label), "fieldtype": "Int", "width": 120} for key, label, _f in STEPS
	]
	data = [
		{**{key: 0 for key, _l, _f in STEPS}, **row}
		for row in sorted(counts.values(), key=lambda r: -sum(r.get(k, 0) for k, _l, _f in STEPS))
	]
	return columns, data
