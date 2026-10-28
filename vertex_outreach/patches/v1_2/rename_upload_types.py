# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

import frappe

from vertex_outreach.vertex_outreach.doctype.email_upload.email_upload import OLD_UPLOAD_TYPES


def execute():
	for old, new in OLD_UPLOAD_TYPES.items():
		frappe.db.sql("UPDATE `tabEmail Upload` SET `upload_type` = %s WHERE `upload_type` = %s", (new, old))
