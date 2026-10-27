# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, now

from vertex_outreach.contacts import (
	CONTACT,
	FRESH,
	INVALID,
	claimed_by,
	classify_emails,
	insert_contacts,
)
from vertex_outreach.emails import scan_emails

ROLES = ("Outreach User", "System Manager")
MANUAL_SOURCE = "Manual check"
MAX_EMAILS_PER_CHECK = 5000


@frappe.whitelist(methods=["POST"])
def check_emails(emails: str, claim: int = 0):
	"""Check pasted text for emails already in the system; optionally claim the fresh ones.

	Returns {"results": [{original, email, verdict, ...details}], "summary": {verdict: count},
	"claimed": [emails inserted by this call]}.
	"""
	claim = cint(claim)
	frappe.only_for(ROLES)
	frappe.has_permission(CONTACT, "create" if claim else "read", throw=True)

	found = scan_emails(emails or "")
	if len(found) > MAX_EMAILS_PER_CHECK:
		frappe.throw(
			_("Too many emails ({0}). Check at most {1} at a time, or use an Email Upload.").format(
				len(found), MAX_EMAILS_PER_CHECK
			)
		)

	valid = list(dict.fromkeys(e for _original, e in found if e))
	info = classify_emails(valid)

	claimed = []
	if claim:
		fresh = [e for e in valid if info[e]["verdict"] == FRESH]
		user = frappe.session.user
		ts = now()
		insert_contacts(fresh, "Contacted", user=user, source=MANUAL_SOURCE, last_contacted_on=ts, timestamp=ts)
		# INSERT IGNORE skips anything someone else claimed in the meantime; only ours match this stamp
		won = claimed_by(fresh, owner=user, creation=ts)
		claimed = [e for e in fresh if e in won]
		if lost := [e for e in fresh if e not in won]:
			info.update(classify_emails(lost))
		for e in claimed:
			info[e]["claimed"] = 1

	results = [
		{"original": original, "email": email, **(info[email] if email else {"verdict": INVALID})}
		for original, email in found
	]
	summary = {}
	for row in results:
		summary[row["verdict"]] = summary.get(row["verdict"], 0) + 1

	return {"results": results, "summary": summary, "claimed": claimed}
