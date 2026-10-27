# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Kitchen display and ticket lifecycle: New → Preparing → Ready → Served, recall, reprint, recovery.

Attribution is always the logged-in user (review finding: Mosaic accepted a caller-supplied verifier).
Every change checks the station's register assignment and moves along the ticket state machine.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, time_diff_in_seconds

from nest_restaurant.core import kitchen as routing
from nest_restaurant.core.fsm import KITCHEN_TICKET
from nest_restaurant.core.money import D
from nest_restaurant.kit import access, audit, realtime
from nest_restaurant.services import orders

TICKET = "Nest Restaurant Kitchen Ticket"
STATION = "Nest Restaurant Station"
STAMP_FIELD = {"Preparing": "started_at", "Ready": "ready_at", "Served": "served_at"}


def _station(name: str):
	st = frappe.get_cached_doc(STATION, name)
	access.require("kitchen", "cashier", "waiter", "supervisor", "manager")
	access.require_register(st.register)
	return st


def board(station: str, include_served_minutes: int = 15) -> dict:
	st = _station(station)
	tickets = frappe.get_all(
		TICKET,
		filters={"station": station, "status": ["in", ["New", "Preparing", "Ready"]]},
		fields=["name", "order", "status", "kind", "table_label", "order_number", "service_type", "sent_at", "started_at", "ready_at", "print_count"],
		order_by="sent_at asc",
		limit_page_length=200,
	)
	lines = frappe.get_all(
		"Nest Restaurant Kitchen Ticket Line",
		{"parent": ["in", [t.name for t in tickets] or ["__none__"]]},
		["parent", "item_name", "qty", "course", "seat", "note", "modifiers"],
		order_by="idx asc",
	)
	by_parent: dict[str, list] = {}
	for l in lines:
		by_parent.setdefault(l.parent, []).append(l)
	now = now_datetime()
	for t in tickets:
		t["lines"] = by_parent.get(t.name, [])
		age = time_diff_in_seconds(now, t.sent_at) / 60 if t.sent_at else 0
		t["age_minutes"] = round(age, 1)
		t["timing"] = routing.minutes_late(age, cint(st.warn_after_minutes) or 10, cint(st.late_after_minutes) or 20)
	return {"station": station, "station_name": st.station_name, "tickets": tickets, "server_time": str(now)}


def set_status(ticket: str, status: str) -> dict:
	frappe.db.get_value(TICKET, ticket, "name", for_update=True)
	doc = frappe.get_doc(TICKET, ticket)
	_station(doc.station)
	KITCHEN_TICKET.assert_transition(doc.status, status)
	if status == doc.status:
		return {"ticket": doc.name, "status": doc.status}
	recall = (doc.status, status) in (("Preparing", "New"), ("Ready", "Preparing"), ("Served", "Ready"))
	doc.status = status
	if status in STAMP_FIELD:
		doc.set(STAMP_FIELD[status], now_datetime())
	doc.flags.ignore_permissions = True  # authorised by station/register assignment above
	doc.save()
	if recall:
		audit.log("ticket.recall", TICKET, doc.name, register=doc.register, to=status)
	realtime.to_doc(STATION, doc.station, "ticket", {"ticket": doc.name, "status": status})
	realtime.to_register(doc.register, "ticket", {"ticket": doc.name, "order": doc.order, "status": status})
	return {"ticket": doc.name, "status": doc.status}


def reprint(ticket: str) -> dict:
	"""Returns a printable payload explicitly marked as a reprint, and counts it."""
	doc = frappe.get_doc(TICKET, ticket)
	_station(doc.station)
	doc.print_count = cint(doc.print_count) + 1
	doc.flags.ignore_permissions = True
	doc.save()
	audit.log("ticket.reprint", TICKET, doc.name, register=doc.register, count=doc.print_count)
	return {
		"ticket": doc.name,
		"reprint": doc.print_count > 1,
		"banner": _("REPRINT {0}").format(doc.print_count - 1) if doc.print_count > 1 else None,
		"station": doc.station,
		"table_label": doc.table_label,
		"order_number": doc.order_number,
		"kind": doc.kind,
		"lines": [{"item_name": l.item_name, "qty": l.qty, "note": l.note, "modifiers": l.modifiers, "course": l.course} for l in doc.lines],
	}


def verify_and_recover(order: str) -> list[str]:
	"""Compare what the order says was sent with what tickets carry, per station and line, and create
	Recovery tickets only for genuine gaps. Each station is grouped independently, so a recovered
	ticket can never carry another station's items (review finding 5)."""
	doc = frappe.get_doc(orders.ORDER, order)
	names = {l.line_id: l.item_name for l in doc.lines}
	stations = orders._stations(doc.register)
	lines = orders._order_lines(doc)
	ticketed: dict = {}
	rows = frappe.db.sql(
		f"""select t.station, l.line_id, sum(l.qty) qty from `tab{TICKET}` t
		join `tabNest Restaurant Kitchen Ticket Line` l on l.parent = t.name
		where t.`order` = %s group by t.station, l.line_id""",
		order,
		as_dict=True,
	)
	for r in rows:
		ticketed[(r.station, r.line_id)] = D(r.qty)
	missing = routing.recover_missing(lines, stations, ticketed)
	created = []
	for t in missing:
		ticket = frappe.get_doc(
			{
				"doctype": TICKET,
				"order": order,
				"station": t.station,
				"register": doc.register,
				"status": "New",
				"kind": "Recovery",
				"table_label": frappe.db.get_value("Nest Restaurant Table", doc.table, "table_label") if doc.table else None,
				"order_number": doc.order_number,
				"service_type": doc.service_type,
				"sent_at": now_datetime(),
				"lines": [{"line_id": tl.line_id, "item_code": tl.item_code, "item_name": names.get(tl.line_id, tl.item_code), "qty": flt(tl.qty), "course": tl.course,
					"seat": tl.seat, "note": tl.note, "modifiers": ", ".join(tl.modifiers)} for tl in t.lines],
			}
		)
		ticket.flags.ignore_permissions = True
		ticket.insert()
		created.append(ticket.name)
		audit.log("ticket.recovered", TICKET, ticket.name, register=doc.register, order=order, station=t.station)
	return created


def recovery_sweep() -> None:
	"""Scheduler (every 10 minutes): verify today's open orders."""
	for name in frappe.get_all(orders.ORDER, {"status": ["in", ["Open", "Bill Requested", "Billed", "Partly Paid"]], "business_date": frappe.utils.nowdate()}, pluck="name"):
		verify_and_recover(name)
