# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

from vertex_outreach.access import restrict_standard_workspaces


def execute():
	"""Only System Managers see Users, Website, Tools, Integrations, Build, ...; checkers see Outreach."""
	restrict_standard_workspaces()
