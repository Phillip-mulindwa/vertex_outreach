# Copyright (c) 2026, Vertex International Recruitment and contributors
# For license information, please see license.txt

"""Import a whole folder of lead files (emails and/or WhatsApp numbers) from the command line.

	bench --site <site> execute vertex_outreach.bulk.import_folder \
		--kwargs "{'path': '/path/to/folder', 'upload_type': 'Already Contacted'}"

Each file becomes its own Email Upload (with the file attached privately) and is processed
synchronously by the same code the background job uses, so Desk shows per-file history and counts.
"""

import os
import time

import frappe

from vertex_outreach.vertex_outreach.doctype.email_upload.email_upload import process_upload

EXTENSIONS = (".csv", ".xlsx", ".xlsm", ".pdf", ".txt")
UPLOAD_TYPES = ("Scraped Leads", "Already Contacted", "Signed Partners")
COUNT_FIELDS = (
	"total_found",
	"new_count",
	"duplicate_count",
	"partner_count",
	"conflict_count",
	"excluded_count",
	"invalid_count",
)


def import_folder(
	path: str,
	upload_type: str = "Already Contacted",
	source: str | None = None,
	default_country: str | None = None,
):
	root = os.path.abspath(os.path.expanduser(path))
	if not os.path.isdir(root):
		frappe.throw(f"Not a folder: {root}")
	if upload_type not in UPLOAD_TYPES:
		frappe.throw(f"upload_type must be one of: {', '.join(UPLOAD_TYPES)}")

	files = _find_files(root)
	print(f"{len(files)} file(s) in {root} -> {upload_type}", flush=True)

	totals = dict.fromkeys(COUNT_FIELDS, 0)
	done, failed = [], []
	started = time.monotonic()
	for i, file_path in enumerate(files, 1):
		rel = os.path.relpath(file_path, root)
		t0 = time.monotonic()
		try:
			name = _create_upload(
				file_path, upload_type, source or os.path.basename(file_path), default_country
			)
			frappe.db.commit()
			process_upload(name)  # commits its own result, and records failures on the upload
			result = frappe.db.get_value(
				"Email Upload", name, ["status", "error_log", *COUNT_FIELDS], as_dict=True
			)
		except Exception:
			frappe.db.rollback()
			name, result = None, frappe._dict(status="Failed", error_log=frappe.get_traceback())

		seconds = time.monotonic() - t0
		if result.status == "Done":
			done.append(name)
			for field in COUNT_FIELDS:
				totals[field] += result[field] or 0
			print(
				f"[{i}/{len(files)}] {rel} ({name}): found {result.total_found}, new {result.new_count}, "
				f"duplicate {result.duplicate_count}, partner {result.partner_count}, "
				f"conflict {result.conflict_count}, excluded {result.excluded_count}, "
				f"invalid {result.invalid_count}, {seconds:.1f}s",
				flush=True,
			)
		else:
			failed.append(name or rel)
			reason = (result.error_log or "").strip().splitlines()[-1:] or ["unknown error"]
			print(
				f"[{i}/{len(files)}] {rel} ({name or 'not created'}): FAILED - {reason[0]}, {seconds:.1f}s",
				flush=True,
			)

	elapsed = time.monotonic() - started
	print(
		f"Total: {len(files)} file(s), {len(done)} done, {len(failed)} failed | found {totals['total_found']}, "
		f"new {totals['new_count']}, duplicate {totals['duplicate_count']}, partner {totals['partner_count']}, "
		f"conflict {totals['conflict_count']}, excluded {totals['excluded_count']}, "
		f"invalid {totals['invalid_count']} | {elapsed:.1f}s",
		flush=True,
	)
	return {"files": len(files), "done": done, "failed": failed, **totals, "seconds": round(elapsed, 1)}


def _find_files(root: str) -> list[str]:
	found = []
	for dirpath, dirnames, filenames in os.walk(root):
		dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
		for filename in sorted(filenames):
			# skip hidden files and Office lock files (~$report.xlsx)
			if filename.startswith((".", "~$")) or not filename.lower().endswith(EXTENSIONS):
				continue
			found.append(os.path.join(dirpath, filename))
	return found


def _create_upload(file_path: str, upload_type: str, source: str, default_country: str | None) -> str:
	with open(file_path, "rb") as f:
		content = f.read()
	file_doc = frappe.get_doc(
		{"doctype": "File", "file_name": os.path.basename(file_path), "is_private": 1, "content": content}
	).insert(ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "Email Upload",
			"upload_type": upload_type,
			"source": source,
			"file": file_doc.file_url,
			"default_country": default_country,
			# Anything but Pending, so saving doesn't also queue a background job
			"status": "Queued",
		}
	).insert(ignore_permissions=True)
	file_doc.db_set(
		{"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "attached_to_field": "file"}
	)
	return doc.name
