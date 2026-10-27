# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""The running check: open, add rounds, edit, send to production, transfer, merge, bill, cancel.

Saving an order, sending it to production, printing a bill, receiving payment and posting an invoice
are distinct steps with distinct records (Order, Kitchen Ticket, Invoice). Every mutating command is
idempotent through the Order Request ledger, and every write locks the order row first, so waiter and
guest additions arriving together are applied one after another and none is lost.
"""

from __future__ import annotations

import json
import secrets
import uuid

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate

from nest_restaurant.core import kitchen as routing
from nest_restaurant.core.fsm import RESTAURANT_ORDER, TABLE
from nest_restaurant.core.money import D
from nest_restaurant.core.payloads import clean_lines, clean_note
from nest_restaurant.kit import access, audit, catalog, pins, realtime, requests

ORDER = "Nest Restaurant Order"
TABLE_DT = "Nest Restaurant Table"
TICKET = "Nest Restaurant Kitchen Ticket"
STATION = "Nest Restaurant Station"
MENU_ITEM = "Nest Restaurant Menu Item"
REQUEST = "Nest Restaurant Order Request"
EDITABLE = ("Open", "Bill Requested")


# --------------------------------------------------------------------------------------- helpers


def _locked_order(name: str):
	if not frappe.db.get_value(ORDER, name, "name", for_update=True):
		frappe.throw(_("Order not found"), frappe.DoesNotExistError)
	return frappe.get_doc(ORDER, name)


def _require_staff(register: str, *roles: str):
	access.require(*(roles or ("cashier", "waiter", "supervisor", "manager")))
	return access.require_register(register)


def _move_order(doc, target: str) -> None:
	RESTAURANT_ORDER.assert_transition(doc.status, target)
	doc.status = target


def _move_table(table_name: str, target: str, order: str | None = None) -> None:
	frappe.db.get_value(TABLE_DT, table_name, "name", for_update=True)
	t = frappe.get_doc(TABLE_DT, table_name)
	TABLE.assert_transition(t.status, target)
	t.status = target
	t.current_order = order if target == "Occupied" else None
	t.version = cint(t.version) + 1
	t.flags.ignore_permissions = True  # floor state follows order state; authorised by the caller
	t.save()
	realtime.to_register(t.register, "table", {"table": t.name, "status": t.status, "order": t.current_order, "version": t.version})


def _save(doc, actor: str | None = None) -> None:
	doc.version = cint(doc.version) + 1
	doc.subtotal_preview = sum(flt(l.qty) * flt(l.rate_preview) for l in doc.lines if not l.void_reason)
	doc.flags.ignore_permissions = True  # orders are written only through this service
	doc.save()
	realtime.to_register(doc.register, "order", {"order": doc.name, "version": doc.version, "status": doc.status, "actor": actor})


def _next_order_number(register: str) -> int:
	key = f"nest_rest:order_no:{register}:{nowdate()}"
	return cint(frappe.cache.incr(key))


def _idempotent(action: str, order: str | None, request_key: str, payload: dict, actor: str):
	outcome, req = requests.begin(REQUEST, request_key, {"action": action, "order": order, **payload}, {"order": order, "action": action, "actor": actor})
	if outcome == "replay":
		stored = frappe.db.get_value(REQUEST, req, "result")
		return req, (json.loads(stored) if stored else {"replayed": True, "order": order})
	return req, None


def _finish(req: str, result: dict) -> dict:
	frappe.db.set_value(REQUEST, req, "result", json.dumps(result, default=str), update_modified=False)
	return result


# ------------------------------------------------------------------------------------------ open


def open_order(register: str, table: str | None, covers: int, service_type: str, request_key: str, actor: str | None = None) -> dict:
	"""`actor="Guest"` is only passed by services.guests after it has validated a signed table context."""
	if actor != "Guest":
		_require_staff(register)
	if service_type not in ("Dine-in", "Takeaway", "Delivery", "Aggregator"):
		frappe.throw(_("Unknown service type"))
	actor = actor or frappe.session.user
	req, replay = _idempotent("open", None, request_key, {"table": table, "covers": covers, "service": service_type}, actor)
	if replay:
		return replay
	if service_type == "Dine-in":
		if not table:
			frappe.throw(_("Choose a table."))
		frappe.db.get_value(TABLE_DT, table, "name", for_update=True)
		t = frappe.get_doc(TABLE_DT, table)
		if t.register != register:
			frappe.throw(_("Table {0} belongs to another register.").format(t.table_label), frappe.PermissionError)
		if t.current_order and frappe.db.get_value(ORDER, t.current_order, "status") in EDITABLE + ("Billed", "Partly Paid"):
			return _finish(req, {"order": t.current_order, "existing": True})
		if t.status not in ("Free", "Reserved"):
			frappe.throw(_("Table {0} is {1}.").format(t.table_label, _(t.status).lower()))
	doc = frappe.get_doc(
		{
			"doctype": ORDER,
			"register": register,
			"service_type": service_type,
			"table": table if service_type == "Dine-in" else None,
			"covers": max(cint(covers), 0),
			"status": "Open",
			"waiter": actor if actor != "Guest" else None,
			"order_number": _next_order_number(register),
			"business_date": nowdate(),
			"visit_code": f"{secrets.randbelow(10000):04d}",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	if doc.table:
		_move_table(doc.table, "Occupied", doc.name)
	realtime.to_register(register, "order", {"order": doc.name, "version": 0, "status": "Open"})
	return _finish(req, {"order": doc.name, "existing": False, "order_number": doc.order_number})


# -------------------------------------------------------------------------------------- read view


def view(name: str, for_guest: bool = False) -> dict:
	doc = frappe.get_doc(ORDER, name)
	if not for_guest:
		_require_staff(doc.register, "cashier", "waiter", "kitchen", "supervisor", "manager")
	tickets = frappe.get_all(TICKET, {"order": name}, ["name", "station", "status", "kind", "sent_at"], order_by="creation asc")
	ticket_lines = frappe.get_all(
		"Nest Restaurant Kitchen Ticket Line", {"parent": ["in", [t.name for t in tickets] or ["__none__"]]}, ["parent", "line_id", "qty"]
	)
	status_of = {t.name: t.status for t in tickets}
	line_progress: dict[str, dict] = {}
	for tl in ticket_lines:
		p = line_progress.setdefault(tl.line_id, {})
		p[status_of[tl.parent]] = p.get(status_of[tl.parent], 0) + flt(tl.qty)
	out = {
		"order": doc.name,
		"version": doc.version,
		"status": doc.status,
		"service_type": doc.service_type,
		"table": doc.table,
		"table_label": frappe.db.get_value(TABLE_DT, doc.table, "table_label") if doc.table else None,
		"covers": doc.covers,
		"order_number": doc.order_number,
		"subtotal_preview": doc.subtotal_preview,
		"paid_amount": doc.paid_amount,
		"lines": [
			{
				"line_id": l.line_id,
				"item_code": l.item_code,
				"item_name": l.item_name,
				"qty": l.qty,
				"sent_qty": l.sent_qty,
				"paid_qty": l.paid_qty,
				"rate_preview": l.rate_preview,
				"course": l.course,
				"seat": l.seat,
				"held": l.held,
				"note": l.note,
				"modifiers": json.loads(l.modifiers or "[]"),
				"source": l.source,
				"void_reason": l.void_reason,
				"progress": line_progress.get(l.line_id, {}),
			}
			for l in doc.lines
		],
	}
	if not for_guest:
		out.update(
			{
				"waiter": doc.waiter,
				"visit_code": doc.visit_code,
				"tickets": tickets,
				"invoices": [{"invoice": i.invoice, "amount": i.amount, "part": i.split_label} for i in doc.invoices],
			}
		)
	return out


# ------------------------------------------------------------------------------------- add lines


def menu_index(register: str) -> dict:
	rows = frappe.get_all(
		MENU_ITEM,
		{"register": register, "sold_out": 0},
		["name", "item_code", "display_name", "default_course", "guest_visible", "available_from", "available_to"],
	)
	return {r.item_code: r for r in rows}


def _allowed_modifiers(menu_row_name: str) -> dict[str, dict]:
	groups = frappe.get_all("Nest Restaurant Menu Item Modifier", {"parent": menu_row_name}, pluck="modifier_group")
	allowed = {}
	for g in groups:
		grp = frappe.get_cached_doc("Nest Restaurant Modifier Group", g)
		for o in grp.options:
			if not o.sold_out:
				allowed[o.option_code] = {"name": o.option_name, "group": g, "price_item": o.price_item}
	return allowed


def _validate_modifier_counts(menu_row_name: str, chosen: list[str]) -> None:
	for g in frappe.get_all("Nest Restaurant Menu Item Modifier", {"parent": menu_row_name}, pluck="modifier_group"):
		grp = frappe.get_cached_doc("Nest Restaurant Modifier Group", g)
		codes = {o.option_code for o in grp.options}
		n = sum(1 for c in chosen if c in codes)
		if n < cint(grp.min_select) or (cint(grp.max_select) and n > cint(grp.max_select)):
			frappe.throw(_("{0}: choose between {1} and {2}.").format(grp.group_name, grp.min_select, grp.max_select))


def add_lines(name: str, raw_lines, request_key: str, source: str = "Staff", actor: str | None = None, guest_only: bool = False) -> dict:
	actor = actor or frappe.session.user
	doc = _locked_order(name)
	if source == "Staff":
		_require_staff(doc.register, "cashier", "waiter", "supervisor", "manager")
	req, replay = _idempotent("add", name, request_key, {"lines": raw_lines}, actor)
	if replay:
		return replay
	if doc.status not in EDITABLE:
		frappe.throw(_("This check is {0}; reopen it to add items.").format(_(doc.status).lower()))
	menu = menu_index(doc.register)
	if guest_only:
		menu = {k: v for k, v in menu.items() if v.guest_visible}
	lines = clean_lines(raw_lines, set(menu))
	profile = frappe.db.get_value("Nest Restaurant Register", doc.register, "pos_profile")
	prices = catalog._price_map(frappe.get_cached_value("POS Profile", profile, "selling_price_list"), [l["item_code"] for l in lines])
	added = []
	for l in lines:
		m = menu[l["item_code"]]
		allowed = _allowed_modifiers(m.name)
		bad = [c for c in l["modifiers"] if c not in allowed]
		if bad:
			frappe.throw(_("An option is no longer available for {0}.").format(m.display_name or l["item_code"]))
		_validate_modifier_counts(m.name, l["modifiers"])
		line_id = uuid.uuid4().hex[:12]
		doc.append(
			"lines",
			{
				"line_id": line_id,
				"item_code": l["item_code"],
				"item_name": m.display_name or frappe.get_cached_value("Item", l["item_code"], "item_name"),
				"qty": flt(l["qty"]),
				"sent_qty": 0,
				"paid_qty": 0,
				"rate_preview": (prices.get(l["item_code"]) or {}).get("rate") or 0,
				"course": l["course"] if source == "Staff" else cint(m.default_course) or 1,
				"seat": l["seat"],
				"held": 0,
				"note": l["note"],
				"modifiers": json.dumps([{"code": c, **allowed[c]} for c in l["modifiers"]]),
				"added_by": actor if actor != "Guest" else None,
				"source": source,
			},
		)
		added.append(line_id)
	if doc.status == "Bill Requested":
		_move_order(doc, "Open")
	_save(doc, actor)
	return _finish(req, {"order": doc.name, "added": added, "version": doc.version})


def update_line(name: str, line_id: str, qty: float, note: str | None, expected_version: int, approval=None, void_reason: str = "") -> dict:
	doc = _locked_order(name)
	_require_staff(doc.register, "cashier", "waiter", "supervisor", "manager")
	if cint(expected_version) != cint(doc.version):
		frappe.throw(
			_("Someone else changed this check. Review the latest version and try again."),
			title=_("Check changed"),
		)
	if doc.status not in EDITABLE:
		frappe.throw(_("This check can't be edited while {0}.").format(_(doc.status).lower()))
	line = next((l for l in doc.lines if l.line_id == line_id), None)
	if not line:
		frappe.throw(_("Line not found"))
	qty = flt(qty)
	if qty < 0:
		frappe.throw(_("Quantity can't be negative."))
	if qty < flt(line.paid_qty):
		frappe.throw(_("That would remove items already paid for."))
	if qty < flt(line.sent_qty):
		if not void_reason.strip():
			frappe.throw(_("Items already sent to the kitchen need a void reason."))
		approver = frappe.session.user if access.is_supervisor() else pins.consume_approval(approval, action="void")
		line.void_reason = void_reason.strip()[:140]
		audit.log("order.void", ORDER, doc.name, register=doc.register, approved_by=approver, line=line_id, item=line.item_code, from_qty=line.qty, to_qty=qty, reason=void_reason)
	line.qty = qty
	if note is not None:
		line.note = clean_note(note)
	_save(doc)
	return {"order": doc.name, "version": doc.version}


# ------------------------------------------------------------------------------------------ send


def _stations(register: str) -> list[routing.Station]:
	out = []
	for s in frappe.get_all(STATION, {"register": register}, ["name", "is_default"]):
		routes = frappe.get_all("Nest Restaurant Station Route", {"parent": s.name}, ["route_type", "value"])
		out.append(
			routing.Station(
				name=s.name,
				item_groups=frozenset(r.value for r in routes if r.route_type == "Item Group"),
				items=frozenset(r.value for r in routes if r.route_type == "Item"),
				is_default=bool(s.is_default),
			)
		)
	return out


def _order_lines(doc) -> list[routing.OrderLine]:
	return [
		routing.OrderLine(
			line_id=l.line_id,
			item_code=l.item_code,
			item_group=frappe.get_cached_value("Item", l.item_code, "item_group"),
			qty=D(l.qty),
			sent_qty=D(l.sent_qty),
			course=cint(l.course) or 1,
			seat=cint(l.seat) or None,
			note=l.note or "",
			modifiers=tuple(m["name"] for m in json.loads(l.modifiers or "[]")),
			held=bool(l.held),
		)
		for l in doc.lines
	]


def send(name: str, request_key: str, fire_courses: list[int] | None = None, actor: str | None = None, kind: str | None = None) -> dict:
	"""Route only the unsent deltas, one ticket per station, in one transaction with sent_qty."""
	actor = actor or frappe.session.user
	doc = _locked_order(name)
	if actor != "Guest":
		_require_staff(doc.register, "cashier", "waiter", "supervisor", "manager")
	req, replay = _idempotent("send", name, request_key, {"courses": fire_courses}, actor)
	if replay:
		return replay
	stations = _stations(doc.register)
	lines = _order_lines(doc)
	tickets, unrouted = routing.route_lines(lines, stations, set(fire_courses) if fire_courses else None)
	if unrouted:
		names = [l.item_code for l in lines if l.line_id in unrouted]
		frappe.throw(_("No kitchen station prepares: {0}. Set up station routing first.").format(", ".join(names)))
	created = []
	table_label = frappe.db.get_value(TABLE_DT, doc.table, "table_label") if doc.table else None
	first_send = not any(flt(l.sent_qty) for l in doc.lines)
	for t in tickets:
		ticket = frappe.get_doc(
			{
				"doctype": TICKET,
				"order": doc.name,
				"station": t.station,
				"register": doc.register,
				"status": "New",
				"kind": kind or ("Void" if t.is_void else "Order" if first_send else "Addition"),
				"table_label": table_label,
				"order_number": doc.order_number,
				"service_type": doc.service_type,
				"sent_by": actor if actor != "Guest" else None,
				"send_key": request_key,
				"sent_at": now_datetime(),
				"lines": [
					{
						"line_id": tl.line_id,
						"item_code": tl.item_code,
						"item_name": next(l.item_name for l in doc.lines if l.line_id == tl.line_id),
						"qty": flt(tl.qty),
						"course": tl.course,
						"seat": tl.seat,
						"note": tl.note,
						"modifiers": ", ".join(tl.modifiers),
					}
					for tl in t.lines
				],
			}
		)
		ticket.flags.ignore_permissions = True
		ticket.insert()
		created.append({"ticket": ticket.name, "station": t.station, "kind": ticket.kind})
		realtime.to_doc(STATION, t.station, "ticket", {"ticket": ticket.name, "status": "New"})
	routing.mark_sent(lines, tickets)
	sent = {l.line_id: l.sent_qty for l in lines}
	for l in doc.lines:
		l.sent_qty = flt(sent[l.line_id])
	_save(doc, actor)
	return _finish(req, {"order": doc.name, "tickets": created, "version": doc.version})


def fire_course(name: str, course: int, request_key: str) -> dict:
	doc = _locked_order(name)
	_require_staff(doc.register, "cashier", "waiter", "supervisor", "manager")
	for l in doc.lines:
		if cint(l.course) == cint(course):
			l.held = 0
	doc.flags.ignore_permissions = True
	doc.save()
	return send(name, request_key, fire_courses=[cint(course)])


def hold_course(name: str, course: int) -> dict:
	doc = _locked_order(name)
	_require_staff(doc.register, "cashier", "waiter", "supervisor", "manager")
	for l in doc.lines:
		if cint(l.course) == cint(course) and flt(l.sent_qty) < flt(l.qty):
			l.held = 1
	_save(doc)
	return {"order": doc.name, "version": doc.version}


# ---------------------------------------------------------------------------- move, merge, cancel


def transfer(name: str, to_table: str, request_key: str) -> dict:
	doc = _locked_order(name)
	_require_staff(doc.register, "cashier", "waiter", "supervisor", "manager")
	req, replay = _idempotent("transfer", name, request_key, {"to": to_table}, frappe.session.user)
	if replay:
		return replay
	target = frappe.get_doc(TABLE_DT, to_table)
	if target.register != doc.register:
		frappe.throw(_("That table belongs to another register."))
	if target.status not in ("Free", "Reserved"):
		frappe.throw(_("Table {0} is in use; merge the checks instead.").format(target.table_label))
	old = doc.table
	if old:
		_move_table(old, "Free")
	_move_table(to_table, "Occupied", doc.name)
	doc.table = to_table
	_save(doc)
	frappe.db.sql(f"update `tab{TICKET}` set table_label=%s where `order`=%s and status in ('New','Preparing','Ready')", (target.table_label, doc.name))
	audit.log("table.transfer", ORDER, doc.name, register=doc.register, from_table=old, to_table=to_table)
	return _finish(req, {"order": doc.name, "table": to_table})


def merge(source: str, target: str, request_key: str) -> dict:
	if source == target:
		frappe.throw(_("Choose two different checks."))
	a, b = sorted([source, target])  # lock in a fixed order so two opposite merges cannot deadlock
	_locked_order(a)
	_locked_order(b)
	src, dst = frappe.get_doc(ORDER, source), frappe.get_doc(ORDER, target)
	_require_staff(src.register, "cashier", "waiter", "supervisor", "manager")
	req, replay = _idempotent("merge", source, request_key, {"into": target}, frappe.session.user)
	if replay:
		return replay
	if src.register != dst.register or src.status not in EDITABLE or dst.status not in EDITABLE:
		frappe.throw(_("Only open checks on the same register can be merged."))
	if any(flt(l.paid_qty) for l in src.lines):
		frappe.throw(_("A partly paid check can't be merged."))
	for l in src.lines:
		dst.append("lines", {k: l.get(k) for k in ("line_id", "item_code", "item_name", "qty", "sent_qty", "paid_qty", "rate_preview",
			"course", "seat", "held", "note", "modifiers", "added_by", "source", "void_reason")})
	dst.covers = cint(dst.covers) + cint(src.covers)
	_move_order(src, "Merged")
	src.merged_into = dst.name
	src.set("lines", [])
	_save(src)
	_save(dst)
	frappe.db.sql(f"update `tab{TICKET}` set `order`=%s where `order`=%s", (dst.name, src.name))
	if src.table:
		_move_table(src.table, "Free")
	audit.log("order.merge", ORDER, dst.name, register=dst.register, merged=src.name)
	return _finish(req, {"order": dst.name, "merged": src.name})


def request_bill(name: str, actor: str | None = None) -> dict:
	doc = _locked_order(name)
	if actor != "Guest":
		_require_staff(doc.register, "cashier", "waiter", "supervisor", "manager")
	if doc.status == "Open":
		_move_order(doc, "Bill Requested")
		_save(doc, actor)
	return {"order": doc.name, "status": doc.status}


def lock_for_billing(name: str) -> dict:
	"""Print the bill: freezes the lines so what the guest sees is what they pay."""
	doc = _locked_order(name)
	_require_staff(doc.register, "cashier", "supervisor", "manager")
	if any(flt(l.sent_qty) < flt(l.qty) and not l.held for l in doc.lines):
		frappe.throw(_("Some items haven't been sent to the kitchen yet."))
	if doc.status in EDITABLE:
		_move_order(doc, "Billed")
		_save(doc)
	audit.log("bill.print", ORDER, doc.name, register=doc.register, version=doc.version)
	return view(doc.name)


def reopen(name: str, approval=None) -> dict:
	doc = _locked_order(name)
	_require_staff(doc.register, "cashier", "supervisor", "manager")
	if doc.status != "Billed":
		frappe.throw(_("Only a billed check can be reopened."))
	approver = frappe.session.user if access.is_supervisor() else pins.consume_approval(approval, action="reopen_bill")
	_move_order(doc, "Open")
	_save(doc)
	audit.log("bill.reopen", ORDER, doc.name, register=doc.register, approved_by=approver)
	return {"order": doc.name, "status": doc.status}


def cancel(name: str, reason: str, request_key: str, approval=None) -> dict:
	doc = _locked_order(name)
	_require_staff(doc.register, "cashier", "waiter", "supervisor", "manager")
	if not (reason or "").strip():
		frappe.throw(_("Give a reason for cancelling."))
	if any(flt(l.paid_qty) for l in doc.lines):
		frappe.throw(_("A check with payments can't be cancelled; refund the payment first."))
	sent = any(flt(l.sent_qty) for l in doc.lines)
	approver = None
	if sent:
		approver = frappe.session.user if access.is_supervisor() else pins.consume_approval(approval, action="void")
		for l in doc.lines:
			l.qty = 0
			l.void_reason = reason[:140]
		doc.flags.ignore_permissions = True
		doc.save()
		send(name, request_key, kind="Void")  # void tickets tell each station what to stop
		doc = _locked_order(name)
	_move_order(doc, "Cancelled")
	doc.cancel_reason = reason.strip()[:500]
	_save(doc)
	if doc.table:
		_move_table(doc.table, "Free")
	audit.log("order.cancel", ORDER, doc.name, register=doc.register, approved_by=approver, reason=reason, after_send=sent)
	return {"order": doc.name, "status": doc.status}


def mark_table_clean(table: str) -> dict:
	t = frappe.get_doc(TABLE_DT, table)
	_require_staff(t.register, "cashier", "waiter", "supervisor", "manager")
	_move_table(table, "Free")
	return {"table": table, "status": "Free"}
