"""Idempotent command ledger.

`begin()` inserts a request row keyed by the client's key *before* any business effect. The unique
index on `request_key` makes concurrent duplicates collide in the database rather than in Python.
Outcomes: `new` (caller proceeds), `replay` (return the stored result), `conflict` (same key, different
payload: rejected with a clear error, never silently resolved).
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from ..core.fingerprint import classify_replay, fingerprint, validate_key


class RequestConflict(frappe.ValidationError):
	pass


def _find(doctype: str, key: str):
	return frappe.db.get_value(doctype, {"request_key": key}, ["name", "fingerprint"], as_dict=True)


def begin(doctype: str, key: str, payload: dict, values: dict) -> tuple[str, str]:
	"""Return (outcome, request name). Row insert is an internal ledger write made after the caller
	was authorised, so it uses ignore_permissions deliberately and only for this ledger doctype."""
	key = validate_key(key)
	fp = fingerprint(payload)
	existing = _find(doctype, key)
	if existing:
		return _outcome(existing, fp)
	frappe.db.savepoint("nest_request")
	try:
		doc = frappe.get_doc(
			{"doctype": doctype, "request_key": key, "fingerprint": fp, "payload": json.dumps(payload, default=str), **values}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		frappe.db.rollback(save_point="nest_request")
		existing = _find(doctype, key)
		if not existing:
			raise
		return _outcome(existing, fp)
	return "new", doc.name


def _outcome(existing, fp: str) -> tuple[str, str]:
	result = classify_replay(existing.fingerprint, fp)
	if result == "conflict":
		frappe.throw(
			_("This request key was already used for a different sale. Start a new sale instead of retrying."),
			RequestConflict,
			title=_("Duplicate request"),
		)
	return result, existing.name
