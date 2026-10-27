"""Idempotent setup: roles, custom fields on ERPNext invoices, settings defaults.

Safe to run on every migrate. Touches only this app's own names (`<field_prefix>_*`, `<prefix> …`),
so installing, upgrading or removing one Nest app never changes the other's configuration.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from ..appspec import SPEC
from . import access

INVOICE_DOCTYPES = ("Sales Invoice", "POS Invoice")


def custom_fields() -> dict:
	module = SPEC.modules[0]
	fields = [
		{
			"fieldname": SPEC.fld("section"),
			"fieldtype": "Section Break",
			"label": _("{0} provenance").format(SPEC.prefix),
			"insert_after": "remarks",
			"collapsible": 1,
			"module": module,
		},
		{
			"fieldname": SPEC.fld("session"),
			"fieldtype": "Link",
			"label": _("{0} shift").format(SPEC.prefix),
			"options": SPEC.dt("Register Session"),
			"insert_after": SPEC.fld("section"),
			"read_only": 1,
			"no_copy": 1,
			"search_index": 1,
			"module": module,
		},
		{
			"fieldname": SPEC.fld("request"),
			"fieldtype": "Link",
			"label": _("{0} request").format(SPEC.prefix),
			"options": SPEC.dt("Sale Request"),
			"insert_after": SPEC.fld("session"),
			"read_only": 1,
			"no_copy": 1,
			"module": module,
		},
	]
	for extra in SPEC.extra_invoice_fields:
		fields.append({**extra, "module": module})
	return {dt: fields for dt in INVOICE_DOCTYPES}


def ensure_roles() -> None:
	for role in SPEC.staff_roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def ensure_settings() -> None:
	settings = frappe.get_single(SPEC.dt("Settings"))
	settings.flags.ignore_permissions = True
	settings.save()  # SettingsController.validate mints the signing secret once


def ensure_return_reasons() -> None:
	for reason, restock in ((_("Changed mind"), 1), (_("Damaged"), 0), (_("Wrong item"), 1)):
		if not frappe.db.exists(SPEC.dt("Return Reason"), reason):
			frappe.get_doc({"doctype": SPEC.dt("Return Reason"), "reason": reason, "restock": restock}).insert(
				ignore_permissions=True
			)


def after_install() -> None:
	ensure_roles()
	create_custom_fields(custom_fields(), ignore_validate=True)
	ensure_settings()
	ensure_return_reasons()


def after_migrate() -> None:
	ensure_roles()
	create_custom_fields(custom_fields(), ignore_validate=True)
	ensure_settings()


def guard_invoice(doc, method=None) -> None:
	"""doc_events hook on Sales/POS Invoice. Only acts on invoices that carry this app's shift field,
	so every other invoice in ERPNext is unaffected."""
	session = doc.get(SPEC.fld("session"))
	if not session:
		return
	if method == "validate" and doc.is_new() and doc.flags.get("nest_app") != SPEC.app:
		frappe.throw(
			_("{0} shift links are set by the till only.").format(SPEC.prefix), frappe.PermissionError
		)
	if method == "before_cancel" and not access.is_supervisor():
		frappe.throw(_("Till sales are corrected with a return. Ask a supervisor to cancel."), frappe.PermissionError)
