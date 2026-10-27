# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PartnerDomain(Document):
	def before_insert(self):
		self.domain = (self.domain or "").strip().lower().lstrip("@")
