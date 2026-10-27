"""Append-only audit trail for sensitive actions (price overrides, voids, refunds, reprints,
table transfers, sync resolutions). Secrets and card data are never written here."""

from __future__ import annotations

import json

import frappe

from ..appspec import SPEC

REDACT = {"pin", "password", "token", "secret", "card_number", "cvv", "pan"}


def _clean(detail):
	if isinstance(detail, dict):
		return {k: ("[redacted]" if k.lower() in REDACT else _clean(v)) for k, v in detail.items()}
	if isinstance(detail, list):
		return [_clean(v) for v in detail]
	return detail


def log(action: str, reference_doctype=None, reference_name=None, register=None, approved_by=None, **detail):
	doc = frappe.get_doc(
		{
			"doctype": SPEC.dt("Audit Log"),
			"action": action,
			"user": frappe.session.user,
			"approved_by": approved_by,
			"register": register,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"detail": json.dumps(_clean(detail), default=str),
		}
	)
	doc.flags.ignore_permissions = True  # system-written trail; readers still need Manager rights
	doc.insert()
	return doc.name
