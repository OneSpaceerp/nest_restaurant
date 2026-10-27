# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Public endpoints for table guests and online bookings. Opaque tokens, rate limits, bounded payloads."""

import frappe
from frappe.rate_limiter import rate_limit

from nest_restaurant.kit.util import obj
from nest_restaurant.services import bookings, guests


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=600)
def start(code: str) -> dict:
	return guests.start_visit((code or "")[:600])


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=600)
def confirm(token: str, visit_code: str) -> dict:
	return guests.confirm(token, (visit_code or "")[:8])


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=60, seconds=60)
def menu(token: str) -> dict:
	return guests.menu(token)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=12, seconds=60)
def submit(token: str, lines, request_key: str) -> dict:
	return guests.submit(token, obj(lines, []), request_key)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=120, seconds=60)
def status(token: str) -> dict:
	return guests.status(token)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=300)
def service_request(token: str, request_type: str) -> dict:
	return guests.service_request(token, request_type)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=60, seconds=60)
def availability(register_name: str, day: str) -> dict:
	return bookings.availability(register_name, day)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=600)
def book(register_name: str, guest_name: str, phone: str, party: int, start: str, request_key: str, notes: str = "", email: str = "", website: str = "") -> dict:
	if website:  # honeypot: humans never see or fill this field
		frappe.throw("Request rejected", frappe.PermissionError)
	return bookings.book_online(register_name, guest_name, phone, party, start, request_key, notes, email)
