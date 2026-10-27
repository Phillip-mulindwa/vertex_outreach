# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

"""Text extraction, email discovery and normalization for outreach uploads."""

import csv
import io
import re

# Loose on purpose: grab anything shaped like x@y so malformed addresses can be
# counted as invalid instead of silently disappearing.
CANDIDATE_RE = re.compile(r"[^\s<>;,\"'()\[\]{}:|/\\]+@[^\s<>;,\"'()\[\]{}:|/\\]+")

LOCAL_RE = re.compile(r"^[a-z0-9!#$%&*+=?^_`{}~-]+(\.[a-z0-9!#$%&*+=?^_`{}~-]+)*$")
DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
TLD_RE = re.compile(r"^[a-z]{2,63}$")

STRIP_CHARS = " \t\r\n.<>;,\"'()[]{}:"

# Contact.name / email is a varchar(140) primary key.
MAX_EMAIL_LENGTH = 140

GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}

EMAIL_HEADERS = {"email", "e-mail", "email address", "e-mail address", "emails"}
ORGANIZATION_HEADERS = {
	"organization",
	"organisation",
	"company",
	"organization name",
	"organisation name",
	"company name",
}
HEADER_SCAN_ROWS = 20
MAX_ORGANIZATION_LENGTH = 140


def _extension(filename: str) -> str:
	return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _as_bytes(content: bytes | str) -> bytes:
	# File.get_content() returns str when the bytes happen to decode as utf-8
	return content.encode("utf-8") if isinstance(content, str) else content


def _as_text(content: bytes | str) -> str:
	if isinstance(content, str):
		return content.lstrip("\ufeff")
	return content.decode("utf-8-sig", errors="ignore")


def extract_text(filename: str, content: bytes | str) -> str:
	"""Return all readable text from an uploaded file, chosen by extension."""
	ext = _extension(filename)
	if ext in ("pdf", "xlsx", "xlsm"):
		content = _as_bytes(content)

	if ext == "pdf":
		from pypdf import PdfReader

		reader = PdfReader(io.BytesIO(content))
		return "\n".join((page.extract_text() or "") for page in reader.pages)

	if ext in ("xlsx", "xlsm"):
		from openpyxl import load_workbook

		wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
		try:
			parts = []
			for ws in wb.worksheets:
				for row in ws.iter_rows(values_only=True):
					parts.append(" ".join(str(v) for v in row if v is not None))
			return "\n".join(parts)
		finally:
			wb.close()

	return _as_text(content)


def extract_tables(filename: str, content: bytes | str) -> list[list[tuple]] | None:
	"""Rows of each sheet for CSV/XLSX/XLSM files; None for formats without columns."""
	ext = _extension(filename)
	if ext == "csv":
		text = _as_text(content)
		try:
			dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
		except csv.Error:
			dialect = csv.excel
		return [[tuple(row) for row in csv.reader(io.StringIO(text), dialect)]]

	if ext in ("xlsx", "xlsm"):
		from openpyxl import load_workbook

		wb = load_workbook(io.BytesIO(_as_bytes(content)), read_only=True, data_only=True)
		try:
			return [list(ws.iter_rows(values_only=True)) for ws in wb.worksheets]
		finally:
			wb.close()
	return None


def find_partner_emails(filename: str, content: bytes | str) -> tuple[dict[str, str | None], int]:
	"""Emails with their organization, for Signed Partner uploads.

	For each CSV/XLSX sheet with a header row naming an email column and an
	organization/organisation/company column, read the pairs from those columns. Otherwise
	(other sheets, other formats) extract every email, with no organization.
	Returns ({normalized email: organization or None}, count of distinct invalid candidates).
	"""
	tables = extract_tables(filename, content)
	if tables is None:
		emails, invalid_count = find_emails(extract_text(filename, content))
		return dict.fromkeys(emails), invalid_count

	partners: dict[str, str | None] = {}
	invalid: set[str] = set()
	for rows in tables:
		header = _find_partner_header(rows)
		if header is None:
			text = "\n".join(" ".join(str(v) for v in row if v is not None) for row in rows)
			found = [(original, email, None) for original, email in scan_emails(text)]
		else:
			header_row, email_col, org_col = header
			found = []
			for row in rows[header_row + 1 :]:
				email_cell = row[email_col] if email_col < len(row) else None
				org_cell = row[org_col] if org_col < len(row) else None
				organization = str(org_cell).strip()[:MAX_ORGANIZATION_LENGTH] if org_cell is not None else ""
				for original, email in scan_emails(str(email_cell or "")):
					found.append((original, email, organization or None))

		for original, email, organization in found:
			if not email:
				invalid.add(original.lower())
			elif email not in partners or (organization and not partners[email]):
				partners[email] = organization
	return partners, len(invalid)


def _find_partner_header(rows: list[tuple]) -> tuple[int, int, int] | None:
	"""(row index, email column, organization column) of the first header row, if any."""
	for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
		cells = [str(v).strip().lower() if v is not None else "" for v in row]
		email_col = next((c for c, v in enumerate(cells) if v in EMAIL_HEADERS), None)
		org_col = next((c for c, v in enumerate(cells) if v in ORGANIZATION_HEADERS), None)
		if email_col is not None and org_col is not None:
			return i, email_col, org_col
	return None


def normalize_email(raw: str) -> str | None:
	"""Return the canonical form of an address, or None if it is not a valid email."""
	email = raw.strip().strip(STRIP_CHARS).lower()
	if email.startswith("mailto:"):
		email = email[7:]

	if email.count("@") != 1:
		return None
	local, domain = email.split("@")
	if not local or not domain or not LOCAL_RE.match(local):
		return None

	labels = domain.split(".")
	if len(labels) < 2 or not TLD_RE.match(labels[-1]):
		return None
	if not all(DOMAIN_LABEL_RE.match(label) for label in labels):
		return None

	if domain in GMAIL_DOMAINS:
		local = local.split("+", 1)[0].replace(".", "")
		domain = "gmail.com"
		if not local:
			return None

	email = f"{local}@{domain}"
	if len(email) > MAX_EMAIL_LENGTH:
		return None
	return email


def scan_emails(text: str) -> list[tuple[str, str | None]]:
	"""Every distinct email-like string in `text` as (original, normalized or None if invalid),
	in first-seen order."""
	seen: dict[str, str | None] = {}
	for match in CANDIDATE_RE.findall(text):
		original = match.strip(STRIP_CHARS)
		if original not in seen:
			seen[original] = normalize_email(original)
	return list(seen.items())


def find_emails(text: str) -> tuple[list[str], int]:
	"""Find addresses anywhere in `text`.

	Returns (unique normalized emails in first-seen order, count of distinct invalid candidates).
	"""
	valid: dict[str, None] = {}
	invalid: set[str] = set()
	for original, email in scan_emails(text):
		if email:
			valid[email] = None
		else:
			invalid.add(original.lower())
	return list(valid), len(invalid)


def email_domain(email: str) -> str:
	return email.rsplit("@", 1)[1]
