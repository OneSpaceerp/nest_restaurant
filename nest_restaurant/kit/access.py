"""Authorisation helpers. UI hiding is never authorisation: every API calls one of these first."""

from __future__ import annotations

import frappe
from frappe import _

from ..appspec import SPEC

ELEVATED = ("System Manager", "Administrator")


def roles(user: str | None = None) -> set[str]:
	return set(frappe.get_roles(user or frappe.session.user))


def has_any(*keys: str, user: str | None = None) -> bool:
	have = roles(user)
	if have & set(ELEVATED):
		return True
	return any(SPEC.roles.get(k) in have for k in keys if SPEC.roles.get(k))


def require(*keys: str) -> None:
	if frappe.session.user == "Guest" or not has_any(*keys):
		frappe.throw(_("You don't have access to do this."), frappe.PermissionError)


def is_manager(user: str | None = None) -> bool:
	return has_any("manager", user=user)


def is_supervisor(user: str | None = None) -> bool:
	return has_any("supervisor", "manager", user=user)


def register_doc(register: str, for_update: bool = False):
	if not register or not frappe.db.exists(SPEC.dt("Register"), register):
		frappe.throw(_("Unknown register"), frappe.DoesNotExistError)
	if for_update:
		frappe.db.get_value(SPEC.dt("Register"), register, "name", for_update=True)
	return frappe.get_doc(SPEC.dt("Register"), register)


def assigned_registers(user: str | None = None) -> list[str]:
	user = user or frappe.session.user
	child = SPEC.dt("Register User")
	return frappe.get_all(
		child, filters={"user": user, "parenttype": SPEC.dt("Register")}, pluck="parent", distinct=True
	)


def can_use_register(register, user: str | None = None, need_open_rights: bool = False) -> bool:
	user = user or frappe.session.user
	if is_manager(user):
		return True
	doc = register if not isinstance(register, str) else register_doc(register)
	if not doc.enabled:
		return False
	for row in doc.users or []:
		if row.user == user:
			return bool(row.can_open) or not need_open_rights
	return False


def require_register(register: str, need_open_rights: bool = False):
	doc = register_doc(register)
	if not can_use_register(doc, need_open_rights=need_open_rights):
		frappe.throw(_("You are not assigned to register {0}.").format(register), frappe.PermissionError)
	return doc


# ---- permission hooks (wired in hooks.py) -------------------------------------------------------


def register_query(user: str | None = None) -> str:
	user = user or frappe.session.user
	if is_manager(user):
		return ""
	names = assigned_registers(user) or ["__none__"]
	quoted = ", ".join(frappe.db.escape(n) for n in names)
	return f"`tab{SPEC.dt('Register')}`.name in ({quoted})"


def register_has_permission(doc, ptype=None, user=None) -> bool | None:
	"""Frappe has_permission hook: returning False denies; any other value defers to role permissions."""
	user = user or frappe.session.user
	if is_manager(user) or ptype not in (None, "read", "select"):
		return None
	return any(row.user == user for row in (doc.users or []))


def session_query(user: str | None = None) -> str:
	"""Cashiers see their own sessions; supervisors see sessions on registers they are assigned to."""
	user = user or frappe.session.user
	if is_manager(user):
		return ""
	table = f"`tab{SPEC.dt('Register Session')}`"
	if is_supervisor(user):
		names = assigned_registers(user) or ["__none__"]
		quoted = ", ".join(frappe.db.escape(n) for n in names)
		return f"{table}.register in ({quoted})"
	return f"{table}.cashier = {frappe.db.escape(user)}"


def owned_query_factory(doctype_suffix: str, field: str):
	def query(user: str | None = None) -> str:
		user = user or frappe.session.user
		if is_supervisor(user):
			return ""
		return f"`tab{SPEC.dt(doctype_suffix)}`.{field} = {frappe.db.escape(user)}"

	return query


sale_request_query = owned_query_factory("Sale Request", "cashier")


def check_app_permission() -> bool:
	"""Used by add_to_apps_screen: show the tile to staff of this app only."""
	if frappe.session.user == "Administrator":
		return True
	return bool(roles() & (set(SPEC.staff_roles) | {"System Manager"}))
