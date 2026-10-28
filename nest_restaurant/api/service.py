# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Floor, orders, kitchen, settlement and bookings for staff (cashier, waiter, kitchen, manager)."""

import frappe

from nest_restaurant.kit.util import obj
from nest_restaurant.services import bookings, floor, guests, kitchen, orders, settle


@frappe.whitelist()
def floor_state(register_name: str) -> dict:
	return floor.floor_state(register_name)


@frappe.whitelist(methods=["POST"])
def save_plan(register_name: str, tables) -> dict:
	return floor.save_plan(register_name, obj(tables, []))


@frappe.whitelist(methods=["POST"])
def add_table(register_name: str, floor: str, table_label: str, seats: int = 4, shape: str = "Square") -> dict:
	return floor.add_table(register_name, floor, table_label, seats, shape)


@frappe.whitelist(methods=["POST"])
def add_floor(register_name: str, floor_name: str) -> dict:
	return floor.add_floor(register_name, floor_name)


@frappe.whitelist()
def table_qr(table: str) -> dict:
	return floor.table_qr(table)


@frappe.whitelist(methods=["POST"])
def mark_table_clean(table: str) -> dict:
	return orders.mark_table_clean(table)


@frappe.whitelist()
def menu(register_name: str) -> list:
	from nest_restaurant.kit import access

	access.require_register(register_name)
	return frappe.get_list(
		"Nest Restaurant Menu Item",
		filters={"register": register_name},
		fields=["name", "item_code", "display_name", "display_name_ar", "section", "sequence", "sold_out", "default_course",
			"allergens", "dietary", "image"],
		order_by="section asc, sequence asc",
		limit_page_length=1000,
	)


@frappe.whitelist()
def menu_detail(register_name: str) -> dict:
	from nest_restaurant.kit import access

	access.require("cashier", "waiter", "supervisor", "manager")
	access.require_register(register_name)
	return guests.menu_for_register(register_name, guest_only=False)


@frappe.whitelist(methods=["POST"])
def open_order(register_name: str, table: str | None = None, covers: int = 0, service_type: str = "Dine-in", request_key: str = "") -> dict:
	return orders.open_order(register_name, table, covers, service_type, request_key)


@frappe.whitelist()
def get_order(order: str) -> dict:
	return orders.view(order)


@frappe.whitelist(methods=["POST"])
def add_lines(order: str, lines, request_key: str) -> dict:
	return orders.add_lines(order, obj(lines, []), request_key)


@frappe.whitelist(methods=["POST"])
def update_line(order: str, line_id: str, qty: float, expected_version: int, note: str | None = None, void_reason: str = "", approval=None) -> dict:
	return orders.update_line(order, line_id, qty, note, expected_version, obj(approval) or approval, void_reason)


@frappe.whitelist(methods=["POST"])
def send(order: str, request_key: str, courses=None) -> dict:
	return orders.send(order, request_key, obj(courses, []) or None)


@frappe.whitelist(methods=["POST"])
def fire_course(order: str, course: int, request_key: str) -> dict:
	return orders.fire_course(order, course, request_key)


@frappe.whitelist(methods=["POST"])
def hold_course(order: str, course: int) -> dict:
	return orders.hold_course(order, course)


@frappe.whitelist(methods=["POST"])
def transfer(order: str, to_table: str, request_key: str) -> dict:
	return orders.transfer(order, to_table, request_key)


@frappe.whitelist(methods=["POST"])
def merge(source: str, target: str, request_key: str) -> dict:
	return orders.merge(source, target, request_key)


@frappe.whitelist(methods=["POST"])
def print_bill(order: str) -> dict:
	return orders.lock_for_billing(order)


@frappe.whitelist(methods=["POST"])
def reopen(order: str, approval=None) -> dict:
	return orders.reopen(order, obj(approval) or approval)


@frappe.whitelist(methods=["POST"])
def cancel_order(order: str, reason: str, request_key: str, approval=None) -> dict:
	return orders.cancel(order, reason, request_key, obj(approval) or approval)


@frappe.whitelist()
def remaining(order: str) -> dict:
	return settle.remaining(order)


@frappe.whitelist(methods=["POST"])
def pay(order: str, register_name: str, part, tenders, request_key: str, customer: str | None = None,
	service_charge_percent: float | None = None, tip: float = 0) -> dict:
	return settle.settle(order, register_name, obj(part), obj(tenders, []), request_key, customer, service_charge_percent, tip)


@frappe.whitelist()
def stations(register_name: str) -> list:
	from nest_restaurant.kit import access

	access.require("kitchen", "cashier", "waiter", "supervisor", "manager")
	access.require_register(register_name)
	orders.ensure_station(register_name)
	return frappe.get_all(
		"Nest Restaurant Station", {"register": register_name}, ["name", "station_name", "is_default"], order_by="station_name asc"
	)


@frappe.whitelist()
def kitchen_board(station: str) -> dict:
	return kitchen.board(station)


@frappe.whitelist(methods=["POST"])
def ticket_status(ticket: str, status: str) -> dict:
	return kitchen.set_status(ticket, status)


@frappe.whitelist(methods=["POST"])
def reprint_ticket(ticket: str) -> dict:
	return kitchen.reprint(ticket)


@frappe.whitelist(methods=["POST"])
def decide_guest_submission(submission: str, accept: int, reason: str = "") -> dict:
	return guests.decide(submission, bool(int(accept)), reason)


@frappe.whitelist(methods=["POST"])
def resolve_service_request(name: str) -> dict:
	return guests.resolve_service_request(name)


@frappe.whitelist()
def reservations(register_name: str, day: str) -> list:
	return bookings.day_view(register_name, day)


@frappe.whitelist(methods=["POST"])
def reservation_status(name: str, status: str, table: str | None = None) -> dict:
	return bookings.set_status(name, status, table)
