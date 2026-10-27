"""Register sessions (shifts): open, cash movements, X report, close, consolidation follow-up.

Concurrency rule: every sale and every close first locks the session row (SELECT … FOR UPDATE).
A sale needs status Open under that lock; closing flips it to Closing under the same lock. A sale that
started first finishes first; a sale that arrives after the flip is refused. No invoice is orphaned.
"""

from __future__ import annotations

import json
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, nowdate

from ..appspec import SPEC
from ..core import cash
from ..core.fsm import REGISTER_SESSION
from . import access, audit, realtime


def _settings():
	return frappe.get_cached_doc(SPEC.dt("Settings"))


def open_session_for(register: str, user: str | None = None, for_update: bool = False):
	user = user or frappe.session.user
	name = frappe.db.get_value(
		SPEC.dt("Register Session"), {"register": register, "cashier": user, "status": "Open"}, "name"
	)
	if not name:
		return None
	if for_update:
		frappe.db.get_value(SPEC.dt("Register Session"), name, "name", for_update=True)
	return frappe.get_doc(SPEC.dt("Register Session"), name)


def require_open_session(register: str, session: str | None = None):
	"""Lock and return the caller's own open session on this register. The caller's identity is the
	logged-in user — never a value from the payload (review finding: POSpire replay impersonation)."""
	access.require_register(register)
	doc = open_session_for(register, for_update=True)
	if not doc or (session and doc.name != session):
		frappe.throw(
			_("Your shift on {0} is not open. Open the register to continue.").format(register),
			frappe.ValidationError,
			title=_("Register closed"),
		)
	if doc.invoice_mode == "Consolidated" and getdate(doc.business_date) != getdate(nowdate()):
		frappe.throw(_("This consolidated shift started on another day. Close it and open a new one."))
	return doc


def open_session(register: str, floats: list[dict]) -> dict:
	reg = access.require_register(register, need_open_rights=True)
	access.register_doc(register, for_update=True)  # serialise concurrent opens on one register
	if open_session_for(register):
		return {"session": open_session_for(register).name, "already_open": True}
	profile = frappe.get_cached_doc("POS Profile", reg.pos_profile)
	if profile.company != reg.company:
		frappe.throw(_("The register's POS Profile belongs to another company."))
	modes = {p.mode_of_payment for p in profile.payments}
	tenders = []
	for row in floats or []:
		mop = row.get("mode_of_payment")
		if mop not in modes:
			frappe.throw(_("{0} is not a payment method on this POS Profile.").format(mop))
		amount = flt(row.get("amount"))
		if amount < 0:
			frappe.throw(_("An opening float cannot be negative."))
		tenders.append({"mode_of_payment": mop, "opening_amount": amount})
	for mop in sorted(modes - {t["mode_of_payment"] for t in tenders}):
		tenders.append({"mode_of_payment": mop, "opening_amount": 0})

	session = frappe.get_doc(
		{
			"doctype": SPEC.dt("Register Session"),
			"register": register,
			"cashier": frappe.session.user,
			"company": reg.company,
			"pos_profile": reg.pos_profile,
			"invoice_mode": reg.invoice_mode,
			"opened_at": now_datetime(),
			"business_date": nowdate(),
			"status": "Open",
			"tenders": tenders,
		}
	)
	if reg.invoice_mode == "Consolidated":
		session.pos_opening_entry = _open_native_entry(reg, tenders)
	session.flags.ignore_permissions = True  # cashier lacks create on sessions by design; checked above
	session.insert()
	audit.log("register.open", SPEC.dt("Register Session"), session.name, register=register)
	realtime.to_register(register, "session", {"session": session.name, "status": "Open"})
	return {"session": session.name, "already_open": False}


def _open_native_entry(reg, tenders) -> str:
	invoice_type = frappe.db.get_single_value("POS Settings", "invoice_type")
	if invoice_type != "POS Invoice":
		frappe.throw(
			_("Consolidated registers need POS Settings → Invoice Type = POS Invoice. Ask a manager to change it or use a direct register."),
			title=_("Consolidated mode unavailable"),
		)
	if frappe.db.exists("POS Opening Entry", {"pos_profile": reg.pos_profile, "status": "Open", "docstatus": 1}):
		frappe.throw(
			_("POS Profile {0} already has an open POS Opening Entry. ERPNext allows one per profile in consolidated mode.").format(
				reg.pos_profile
			),
			title=_("Profile in use"),
		)
	entry = frappe.get_doc(
		{
			"doctype": "POS Opening Entry",
			"period_start_date": now_datetime(),
			"posting_date": nowdate(),
			"company": reg.company,
			"pos_profile": reg.pos_profile,
			"user": frappe.session.user,
			"balance_details": [
				{"mode_of_payment": t["mode_of_payment"], "opening_amount": t["opening_amount"]} for t in tenders
			],
		}
	)
	entry.insert()  # normal permissions: the cashier needs POS Opening Entry create rights in this mode
	entry.submit()
	return entry.name


def add_cash_movement(register: str, direction: str, amount, reason: str, request_key: str, approved_by=None) -> dict:
	if direction not in ("In", "Out"):
		frappe.throw(_("Choose cash in or cash out."))
	if flt(amount) <= 0:
		frappe.throw(_("Enter an amount above zero."))
	if not (reason or "").strip():
		frappe.throw(_("Give a reason for the cash movement."))
	session = require_open_session(register)
	existing = frappe.db.get_value(SPEC.dt("Cash Movement"), {"request_key": request_key}, "name")
	if existing:
		return {"name": existing, "replay": True}
	cash_mode = _cash_mode(session.pos_profile)
	doc = frappe.get_doc(
		{
			"doctype": SPEC.dt("Cash Movement"),
			"session": session.name,
			"direction": direction,
			"amount": flt(amount),
			"mode_of_payment": cash_mode,
			"reason": reason.strip()[:140],
			"approved_by": approved_by,
			"request_key": request_key,
		}
	)
	doc.flags.ignore_permissions = True  # append-only; authorised via the open-session check
	doc.insert()
	audit.log("cash.movement", SPEC.dt("Cash Movement"), doc.name, register=register, direction=direction, amount=amount)
	return {"name": doc.name, "replay": False}


def _cash_mode(pos_profile: str) -> str | None:
	for p in frappe.get_cached_doc("POS Profile", pos_profile).payments:
		if frappe.get_cached_value("Mode of Payment", p.mode_of_payment, "type") == "Cash":
			return p.mode_of_payment
	return None


def _invoice_doctype(session) -> str:
	return "POS Invoice" if session.invoice_mode == "Consolidated" else "Sales Invoice"


def summary(session_name: str, include_expected: bool = True) -> dict:
	"""X report: totals so far, computed only from this app's invoices for this session."""
	session = frappe.get_doc(SPEC.dt("Register Session"), session_name)
	session.check_permission("read")
	dt = _invoice_doctype(session)
	field = SPEC.fld("session")
	invoices = frappe.get_all(
		dt,
		filters={field: session.name, "docstatus": 1},
		fields=["name", "is_return", "grand_total", "rounded_total", "change_amount"],
	)
	names = [i.name for i in invoices] or ["__none__"]
	payments = frappe.get_all(
		"Sales Invoice Payment",
		filters={"parenttype": dt, "parent": ["in", names]},
		fields=["mode_of_payment", "sum(amount) as amount"],
		group_by="mode_of_payment",
	)
	paid = {p.mode_of_payment: flt(p.amount) for p in payments}
	cash_mode = _cash_mode(session.pos_profile)
	change = sum(flt(i.change_amount) for i in invoices)
	if cash_mode:
		paid[cash_mode] = paid.get(cash_mode, 0) - change
	movements = frappe.get_all(
		SPEC.dt("Cash Movement"), filters={"session": session.name}, fields=["direction", "amount", "mode_of_payment"]
	)
	moved: dict[str, Decimal] = {}
	for m in movements:
		sign = 1 if m.direction == "In" else -1
		moved[m.mode_of_payment] = moved.get(m.mode_of_payment, 0) + sign * flt(m.amount)
	opening = {t.mode_of_payment: flt(t.opening_amount) for t in session.tenders}
	expected = cash.expected_by_mode(opening, paid, {}, moved)
	out = {
		"session": session.name,
		"register": session.register,
		"status": session.status,
		"invoice_mode": session.invoice_mode,
		"sales_count": sum(1 for i in invoices if not i.is_return),
		"returns_count": sum(1 for i in invoices if i.is_return),
		"net_sales": sum(flt(i.rounded_total or i.grand_total) for i in invoices),
		"by_mode": {m: str(v) for m, v in paid.items()},
		"movements": {m: str(v) for m, v in moved.items()},
	}
	reg = frappe.get_cached_doc(SPEC.dt("Register"), session.register)
	if include_expected and not (reg.blind_close and not access.is_supervisor()):
		out["expected"] = {m: str(v) for m, v in expected.items()}
	out["_expected_internal"] = expected
	return out


def close_session(register: str, counts: dict, reason: str = "", denominations: dict | None = None) -> dict:
	session = require_open_session(register)
	_assert_no_unresolved(session)
	report = summary(session.name)
	expected = report.pop("_expected_internal")
	counted = {m: flt(v) for m, v in (counts or {}).items()}
	variance = cash.variance(expected, counted)
	tolerance = flt(_settings().variance_tolerance)
	if cash.needs_reason(variance, tolerance) and not (reason or "").strip():
		frappe.throw(_("The count differs from what was expected. Give a reason to close."), title=_("Variance"))

	REGISTER_SESSION.assert_transition(session.status, "Closing")
	for t in session.tenders:
		t.expected_amount = flt(expected.get(t.mode_of_payment, 0))
		t.counted_amount = flt(counted.get(t.mode_of_payment, t.expected_amount))
		t.variance = flt(variance.get(t.mode_of_payment, 0))
		if denominations and denominations.get(t.mode_of_payment):
			t.denominations = json.dumps(denominations[t.mode_of_payment])
	session.status = "Closing"
	session.sales_count = report["sales_count"]
	session.returns_count = report["returns_count"]
	session.grand_total = report["net_sales"]
	session.variance_reason = (reason or "").strip()[:500]
	session.closed_at = now_datetime()
	session.flags.ignore_permissions = True
	session.save()

	if session.invoice_mode == "Consolidated":
		_close_native(session, counted)
	else:
		session.status = "Closed"
		session.save()
	audit.log("register.close", SPEC.dt("Register Session"), session.name, register=register, variance=variance)
	realtime.to_register(register, "session", {"session": session.name, "status": session.status})
	return {"session": session.name, "status": session.status, "variance": {k: str(v) for k, v in variance.items()}}


def _assert_no_unresolved(session) -> None:
	pending = frappe.db.count(SPEC.dt("Sale Request"), {"session": session.name, "status": ["in", ["Received", "Needs Review"]]})
	if pending:
		frappe.throw(
			_("{0} sale(s) on this shift still need review. Resolve them before closing.").format(pending),
			title=_("Unresolved sales"),
		)


def _close_native(session, counted: dict) -> None:
	from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import make_closing_entry_from_opening

	opening = frappe.get_doc("POS Opening Entry", session.pos_opening_entry)
	closing = make_closing_entry_from_opening(opening)
	for row in closing.payment_reconciliation:
		if row.mode_of_payment in counted:
			row.closing_amount = counted[row.mode_of_payment]
	closing.insert()
	try:
		closing.submit()
	except Exception as e:  # consolidation errors are reported, the session stays recoverable
		frappe.db.rollback()
		session.reload()
		session.status = "Close Failed"
		session.close_error = str(e)[:1000]
		session.flags.ignore_permissions = True
		session.save()
		return
	session.pos_closing_entry = closing.name
	session.status = "Closed" if closing.status in ("Submitted", "") else "Closing"
	session.save()


def follow_up_consolidations() -> None:
	"""Scheduler: settle sessions waiting on ERPNext's queued consolidation."""
	for name in frappe.get_all(SPEC.dt("Register Session"), {"status": "Closing", "invoice_mode": "Consolidated"}, pluck="name"):
		s = frappe.get_doc(SPEC.dt("Register Session"), name)
		if not s.pos_closing_entry:
			continue
		status, error = frappe.db.get_value("POS Closing Entry", s.pos_closing_entry, ["status", "error_message"])
		if status == "Submitted":
			s.status = "Closed"
		elif status == "Failed":
			s.status = "Close Failed"
			s.close_error = (error or "")[:1000]
		else:
			continue
		s.flags.ignore_permissions = True
		s.save()


def retry_close(session_name: str) -> dict:
	access.require("supervisor", "manager")
	s = frappe.get_doc(SPEC.dt("Register Session"), session_name)
	if s.status != "Close Failed":
		frappe.throw(_("Only a failed close can be retried."))
	REGISTER_SESSION.assert_transition(s.status, "Closing")
	s.status = "Closing"
	s.flags.ignore_permissions = True
	s.save()
	if s.pos_closing_entry:
		closing = frappe.get_doc("POS Closing Entry", s.pos_closing_entry)
		closing.retry()
	else:
		_close_native(s, {t.mode_of_payment: t.counted_amount for t in s.tenders})
	audit.log("register.retry_close", SPEC.dt("Register Session"), s.name, register=s.register)
	return {"session": s.name, "status": s.status}


def business_day_open_sessions(max_hours: int = 18) -> list[str]:
	"""Sessions open longer than `max_hours` — surfaced to managers by the scheduler."""
	cutoff = get_datetime(now_datetime()).timestamp() - max_hours * 3600
	rows = frappe.get_all(SPEC.dt("Register Session"), {"status": "Open"}, ["name", "opened_at"])
	return [r.name for r in rows if get_datetime(r.opened_at).timestamp() < cutoff]
