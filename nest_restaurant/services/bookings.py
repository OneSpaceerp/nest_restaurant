# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Reservations: public availability and booking, staff confirmation/seating, capacity under a lock."""

from __future__ import annotations

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime

from nest_restaurant.core import booking
from nest_restaurant.core.fingerprint import validate_key
from nest_restaurant.core.fsm import RESERVATION
from nest_restaurant.core.payloads import clean_note
from nest_restaurant.kit import access, audit, realtime
from nest_restaurant.services import orders

RES = "Nest Restaurant Reservation"
REGISTER = "Nest Restaurant Register"
LIVE = ("Requested", "Confirmed", "Seated")


def _settings():
	s = frappe.get_cached_doc("Nest Restaurant Settings")
	if not s.booking_enabled:
		frappe.throw(_("Online booking is not available."), frappe.PermissionError)
	return s


def _window(s) -> booking.Window:
	return booking.Window(str(s.booking_opens)[:5], str(s.booking_closes)[:5], cint(s.booking_slot_minutes) or 30, cint(s.booking_stay_minutes) or 90)


def _existing(register: str, day) -> list[tuple[datetime, int, int]]:
	start = get_datetime(f"{day} 00:00:00") - timedelta(hours=6)
	end = get_datetime(f"{day} 23:59:59") + timedelta(hours=6)
	rows = frappe.get_all(RES, {"register": register, "status": ["in", LIVE], "start": ["between", [start, end]]}, ["start", "stay_minutes", "party_size"])
	return [(get_datetime(r.start), cint(r.stay_minutes) or 90, cint(r.party_size)) for r in rows]


def availability(register: str, day: str) -> dict:
	s = _settings()
	if not frappe.db.get_value(REGISTER, register, "enabled"):
		frappe.throw(_("Unknown restaurant"))
	win = _window(s)
	d = getdate(day)
	first = get_datetime(f"{d} {win.opens}:00")
	last = get_datetime(f"{d} {win.closes}:00")
	if last <= first:
		last += timedelta(days=1)
	existing = _existing(register, d)
	now = now_datetime()
	slots = []
	t = first
	while t + timedelta(minutes=win.stay_minutes) <= last:
		try:
			booking.validate_slot(t, win, now, cint(s.booking_lead_minutes) or 60)
			used = sum(p for st, m, p in existing if booking.overlaps(t, win.stay_minutes, st, m))
			left = cint(s.booking_online_seats) - used
			slots.append({"time": t.strftime("%H:%M"), "seats_left": max(left, 0) if left < 6 else None, "available": left > 0})
		except booking.BookingError:
			pass
		t += timedelta(minutes=win.slot_minutes)
	return {"date": str(d), "slots": slots, "max_party": cint(s.booking_max_party)}


def book_online(register: str, guest_name: str, phone: str, party: int, start: str, request_key: str, notes: str = "", email: str = "") -> dict:
	s = _settings()
	key = validate_key(request_key)
	existing = frappe.db.get_value(RES, {"request_key": key}, ["name", "status"], as_dict=True)
	if existing:
		return {"reservation": existing.name, "status": existing.status, "replayed": True}
	name = (guest_name or "").strip()[:80]
	phone = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")[:20]
	if not name or len(phone) < 7:
		frappe.throw(_("Give a name and a phone number we can reach."))
	frappe.db.get_value(REGISTER, register, "name", for_update=True)  # serialise bookings for this restaurant
	when = get_datetime(start)
	win = _window(s)
	booking.validate_slot(when, win, now_datetime(), cint(s.booking_lead_minutes) or 60)
	booking.check_capacity(cint(party), when, win.stay_minutes, _existing(register, when.date()), cint(s.booking_online_seats), cint(s.booking_max_party) or 8)
	daily = frappe.db.count(RES, {"phone": phone, "start": ["between", [when.replace(hour=0, minute=0), when.replace(hour=23, minute=59)]], "status": ["in", LIVE]})
	if daily >= 2:
		frappe.throw(_("This phone number already has bookings that day. Call us to change them."))
	doc = frappe.get_doc(
		{
			"doctype": RES,
			"guest_name": name,
			"phone": phone,
			"email": (email or "").strip()[:120] or None,
			"register": register,
			"party_size": cint(party),
			"start": when,
			"stay_minutes": win.stay_minutes,
			"status": "Requested",
			"source": "Online",
			"notes": clean_note(notes),
			"request_key": key,
		}
	)
	doc.flags.ignore_permissions = True  # public booking request; capacity checked under lock above
	doc.insert()
	realtime.to_register(register, "reservation", {"reservation": doc.name, "status": "Requested"})
	return {"reservation": doc.name, "status": doc.status}


def set_status(name: str, status: str, table: str | None = None) -> dict:
	doc = frappe.get_doc(RES, name)
	access.require("cashier", "waiter", "supervisor", "manager")
	access.require_register(doc.register)
	RESERVATION.assert_transition(doc.status, status)
	doc.status = status
	if table:
		t = frappe.db.get_value("Nest Restaurant Table", table, ["register", "seats"], as_dict=True)
		if not t or t.register != doc.register:
			frappe.throw(_("Choose a table in this restaurant."))
		doc.table = table
	if status == "Seated":
		if not doc.table:
			frappe.throw(_("Choose a table to seat the party."))
		opened = orders.open_order(doc.register, doc.table, doc.party_size, "Dine-in", f"rsv-{doc.name}-seat-{now_datetime().strftime('%Y%m%d')}")
		doc.order = opened["order"]
	doc.flags.ignore_permissions = True
	doc.save()
	audit.log("reservation.status", RES, doc.name, register=doc.register, status=status)
	return {"reservation": doc.name, "status": doc.status, "order": doc.order}


def day_view(register: str, day: str) -> list[dict]:
	access.require("cashier", "waiter", "supervisor", "manager")
	access.require_register(register)
	d = getdate(day)
	return frappe.get_list(
		RES,
		filters={"register": register, "start": ["between", [f"{d} 00:00:00", f"{d} 23:59:59"]]},
		fields=["name", "guest_name", "phone", "party_size", "start", "stay_minutes", "table", "status", "source", "notes", "order"],
		order_by="start asc",
	)
