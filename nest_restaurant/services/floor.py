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


def table_qr(table: str) -> dict:
	"""Signed table context for printing on the table. It names the table; it grants nothing."""
	access.require("manager", "supervisor")
	t = frappe.get_doc(TABLE_DT, table)
	access.require_register(t.register)
	secret = frappe.get_single("Nest Restaurant Settings").get_password("signing_secret")
	code = sign_context(secret, "table", {"register": t.register, "table": t.name}, QR_TTL_DAYS * 86400)
	return {"table": t.name, "label": t.table_label, "url": f"/nest-restaurant/customer/t/{code}"}
