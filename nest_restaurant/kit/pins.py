"""Staff PINs, staff switching and single-use manager approvals.

An approval is minted only after the approver's PIN verifies, carries its action and limit, lives in
Redis for a short TTL and is consumed with GETDEL, so a captured approval cannot be replayed.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from ..appspec import SPEC
from ..core import pin as pinlib
from ..core.tokens import hash_token, new_token
from . import access, audit

ACTIONS = {"discount", "price", "refund", "void", "cash_out", "reopen_bill", "reprint"}


class ApprovalError(frappe.PermissionError):
	pass


def _settings():
	return frappe.get_cached_doc(SPEC.dt("Settings"))


def set_pin(new_pin: str, current_pin: str | None = None) -> None:
	user = frappe.session.user
	if user == "Guest" or not access.has_any(*SPEC.roles):
		frappe.throw(_("Only staff can set a PIN."), frappe.PermissionError)
	value = pinlib.validate_new_pin(new_pin)
	dt = SPEC.dt("Staff PIN")
	if frappe.db.exists(dt, user):
		doc = frappe.get_doc(dt, user)
		if doc.pin_hash and not pinlib.verify_pin(current_pin or "", doc.pin_hash):
			frappe.throw(_("Your current PIN is not correct."), frappe.PermissionError)
	else:
		doc = frappe.get_doc({"doctype": dt, "user": user})
	doc.pin_hash = pinlib.hash_pin(value)
	doc.failed_attempts = 0
	doc.locked_until = None
	doc.flags.ignore_permissions = True  # a user may only ever write their own PIN row (checked above)
	doc.save() if not doc.is_new() else doc.insert()
	audit.log("pin.set", dt, user)


def verify(user: str, pin: str) -> bool:
	"""Check `user`'s PIN with lockout. Raises when locked; returns False on a wrong PIN."""
	dt = SPEC.dt("Staff PIN")
	if not frappe.db.exists(dt, user):
		return False
	frappe.db.get_value(dt, user, "name", for_update=True)
	doc = frappe.get_doc(dt, user)
	now = now_datetime()
	if pinlib.is_locked(get_datetime(doc.locked_until) if doc.locked_until else None, now):
		frappe.throw(_("Too many wrong PINs. Try again later."), frappe.PermissionError, title=_("Locked"))
	settings = _settings()
	if doc.pin_hash and pinlib.verify_pin(pin or "", doc.pin_hash):
		if doc.failed_attempts:
			doc.failed_attempts = 0
			doc.locked_until = None
			doc.flags.ignore_permissions = True
			doc.save()
		return True
	failed, until = pinlib.lockout_after_failure(
		cint(doc.failed_attempts), now, cint(settings.pin_max_attempts) or 5, cint(settings.pin_lock_minutes) or 5
	)
	doc.failed_attempts = failed
	doc.locked_until = until
	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()  # persist the failed attempt even though the caller's request will fail  # nosemgrep
	audit.log("pin.failed", dt, user)
	return False


def _cache_key(token: str) -> str:
	return f"{SPEC.field_prefix}:approval:{hash_token(token)}"


def request_approval(register: str, approver: str, pin: str, action: str, max_percent: float = 0) -> dict:
	"""Called from the cashier's device while the approver types their own PIN."""
	access.require_register(register)
	if action not in ACTIONS:
		frappe.throw(_("Unknown approval action"))
	if not access.is_supervisor(approver):
		raise ApprovalError(_("{0} cannot approve this.").format(approver))
	pin_row = frappe.db.get_value(SPEC.dt("Staff PIN"), approver, ["is_approver", "max_discount_percent"], as_dict=True)
	if not pin_row or not pin_row.is_approver:
		raise ApprovalError(_("{0} is not set up as an approver.").format(approver))
	if not verify(approver, pin):
		raise ApprovalError(_("The approver's PIN is not correct."))
	if action == "discount" and flt(max_percent) > flt(pin_row.max_discount_percent or 100):
		raise ApprovalError(_("That discount is above what {0} may approve.").format(approver))
	token = new_token()
	ttl = cint(_settings().approval_ttl_seconds) or 120
	frappe.cache.set_value(
		_cache_key(token),
		json.dumps({"approver": approver, "action": action, "max_percent": flt(max_percent), "cashier": frappe.session.user, "register": register}),
		expires_in_sec=ttl,
	)
	audit.log("approval.granted", register=register, approved_by=approver, action=action, max_percent=max_percent)
	return {"approval": token, "expires_in": ttl, "approver": approver}


def consume_approval(approval: dict | str | None, action: str, max_percent: float = 0) -> str:
	token = approval.get("approval") if isinstance(approval, dict) else approval
	if not token:
		raise ApprovalError(_("This needs a manager's approval."))
	raw = frappe.cache.getdel(frappe.cache.make_key(_cache_key(token)))
	if not raw:
		raise ApprovalError(_("The approval has expired or was already used."))
	data = json.loads(raw)
	if data["action"] != action or data["cashier"] != frappe.session.user:
		raise ApprovalError(_("The approval was for a different action."))
	if flt(max_percent) > flt(data.get("max_percent") or 0) and action == "discount":
		raise ApprovalError(_("The discount is larger than the approval."))
	return data["approver"]
