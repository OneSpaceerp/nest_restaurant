# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Floor plan state for the cashier/waiter views, plan editing, and table QR codes."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, time_diff_in_seconds

from nest_restaurant.core.tokens import sign_context
from nest_restaurant.kit import access, audit

TABLE_DT = "Nest Restaurant Table"
FLOOR = "Nest Restaurant Floor"
ORDER = "Nest Restaurant Order"
QR_TTL_DAYS = 365


def floor_state(register: str) -> dict:
	access.require("cashier", "waiter", "supervisor", "manager")
	access.require_register(register)
	floors = frappe.get_all(FLOOR, {"register": register}, ["name", "floor_name", "width", "height"], order_by="sequence asc")
	tables = frappe.get_all(
		TABLE_DT,
		{"register": register},
		["name", "floor", "table_label", "seats", "status", "shape", "x", "y", "w", "h", "current_order", "version"],
	)
	order_names = [t.current_order for t in tables if t.current_order]
	orders = {
		o.name: o
		for o in frappe.get_all(
			ORDER,
			{"name": ["in", order_names or ["__none__"]]},
			["name", "status", "covers", "waiter", "subtotal_preview", "paid_amount", "creation", "order_number"],
		)
	}
	open_requests = frappe.get_all(
		"Nest Restaurant Service Request", {"status": "Open", "order": ["in", order_names or ["__none__"]]}, ["order", "request_type"]
	)
	ready = frappe.get_all(
		"Nest Restaurant Kitchen Ticket", {"status": "Ready", "order": ["in", order_names or ["__none__"]]}, ["order"]
	)
	now = now_datetime()
	for t in tables:
		o = orders.get(t.current_order)
		if o:
			t["order"] = {
				"name": o.name,
				"status": o.status,
				"covers": o.covers,
				"waiter": o.waiter,
				"subtotal_preview": o.subtotal_preview,
				"paid_amount": o.paid_amount,
				"order_number": o.order_number,
				"age_minutes": round(time_diff_in_seconds(now, o.creation) / 60),
				"requests": [r.request_type for r in open_requests if r.order == o.name],
				"ready_tickets": sum(1 for r in ready if r.order == o.name),
			}
	return {"register": register, "floors": floors, "tables": tables, "server_time": str(now)}


def save_plan(register: str, tables: list[dict]) -> dict:
	access.require("manager")
	access.require_register(register)
	for row in tables or []:
		t = frappe.get_doc(TABLE_DT, row.get("name"))
		if t.register != register:
			frappe.throw(_("Table {0} is on another register.").format(t.table_label))
		for k in ("x", "y", "w", "h", "seats"):
			if k in row:
				t.set(k, max(cint(row[k]), 0))
		if row.get("shape") in ("Square", "Round", "Rectangle"):
			t.shape = row["shape"]
		t.save()  # normal permissions: managers have write on tables
	audit.log("floor.save", register=register, tables=len(tables or []))
	return floor_state(register)


def add_table(register: str, floor: str, table_label: str, seats: int = 4, shape: str = "Square") -> dict:
	"""New table on a floor, placed in the first free spot of a 20-unit grid so it never lands on top
	of another table; the manager then drags it where it belongs."""
	access.require("manager")
	access.require_register(register)
	fl = frappe.get_doc(FLOOR, floor)
	if fl.register != register:
		frappe.throw(_("This floor is on another register."))
	label = " ".join((table_label or "").split())[:40]
	if not label:
		frappe.throw(_("Give the table a name or number."))
	if frappe.db.exists(TABLE_DT, {"floor": floor, "table_label": label}):
		frappe.throw(_("There is already a table {0} on this floor.").format(label))
	shape = shape if shape in ("Square", "Round", "Rectangle") else "Square"
	w, h = (140, 90) if shape == "Rectangle" else (90, 90)
	taken = frappe.get_all(TABLE_DT, {"floor": floor}, ["x", "y", "w", "h"])
	width, height = cint(fl.width) or 1200, cint(fl.height) or 800
	x, y = _free_spot(taken, width, height, w, h)
	doc = frappe.get_doc({"doctype": TABLE_DT, "floor": floor, "table_label": label, "seats": max(cint(seats), 1), "shape": shape, "x": x, "y": y, "w": w, "h": h})
	doc.insert()  # managers have create on tables
	audit.log("floor.table_added", TABLE_DT, doc.name, register=register)
	return floor_state(register)


def _free_spot(taken, width: int, height: int, w: int, h: int, step: int = 20, gap: int = 20) -> tuple[int, int]:
	def clear(x, y):
		return all(
			x + w + gap <= cint(t.x) or cint(t.x) + (cint(t.w) or 90) + gap <= x or y + h + gap <= cint(t.y) or cint(t.y) + (cint(t.h) or 90) + gap <= y
			for t in taken
		)

	for y in range(gap, max(height - h, gap) + 1, step):
		for x in range(gap, max(width - w, gap) + 1, step):
			if clear(x, y):
				return x, y
	return gap, gap


def add_floor(register: str, floor_name: str) -> dict:
	access.require("manager")
	access.require_register(register)
	name = " ".join((floor_name or "").split())[:60]
	if not name:
		frappe.throw(_("Give the floor a name."))
	if frappe.db.exists(FLOOR, {"register": register, "floor_name": name}):
		frappe.throw(_("There is already a floor called {0}.").format(name))
	seq = frappe.db.count(FLOOR, {"register": register})
	frappe.get_doc({"doctype": FLOOR, "register": register, "floor_name": name, "sequence": seq}).insert()
	audit.log("floor.added", FLOOR, name, register=register)
	return floor_state(register)


def table_qr(table: str) -> dict:
	"""Signed table context for printing on the table. It names the table; it grants nothing."""
	access.require("manager", "supervisor")
	t = frappe.get_doc(TABLE_DT, table)
	access.require_register(t.register)
	secret = frappe.get_single("Nest Restaurant Settings").get_password("signing_secret")
	code = sign_context(secret, "table", {"register": t.register, "table": t.name}, QR_TTL_DAYS * 86400)
	return {"table": t.name, "label": t.table_label, "url": f"/nest-restaurant/customer/t/{code}"}
