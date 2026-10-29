# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Settlement: each paid part of a check becomes one ordinary ERPNext invoice.

Parts are chosen by items, by seat, or as "everything left". Modifier add-ons with a price item and the
service charge / tip become their own invoice lines, so prices, taxes and stock come from ERPNext.
Dish recipes use ERPNext Product Bundles: the sold dish is a non-stock bundle whose packed items
(ingredients) are consumed by the invoice — the dish itself is never also consumed, so there is no
double consumption.
"""

from __future__ import annotations

import json
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, flt

from nest_restaurant.core import split as splitting
from nest_restaurant.core.fsm import TABLE
from nest_restaurant.core.money import D
from nest_restaurant.kit import access, audit, invoicing, realtime
from nest_restaurant.services import orders

ORDER = orders.ORDER


def _settings():
	return frappe.get_cached_doc("Nest Restaurant Settings")


def _portions(doc, part: dict) -> list[dict]:
	open_lines = [l for l in doc.lines if flt(l.qty) > flt(l.paid_qty)]
	if not open_lines:
		frappe.throw(_("Everything on this check is paid."))
	mode = part.get("mode") or "all"
	if mode == "all":
		return [{"line_id": l.line_id, "qty": D(l.qty) - D(l.paid_qty)} for l in open_lines]
	check = [splitting.CheckLine(l.line_id, D(l.qty), D(l.qty) * D(l.rate_preview), cint(l.seat) or None, D(l.paid_qty)) for l in doc.lines if flt(l.qty)]
	if mode == "items":
		chosen = splitting.by_items(check, {k: D(v) for k, v in (part.get("selection") or {}).items()})
		return [{"line_id": c["line_id"], "qty": c["qty"]} for c in chosen]
	if mode == "seat":
		seats = splitting.by_seat(check)
		rows = seats.get(str(cint(part.get("seat"))))
		if not rows:
			frappe.throw(_("Nothing is left to pay for seat {0}.").format(part.get("seat")))
		shared = [r for r in rows if r.get("shared")]
		if shared:
			frappe.throw(_("Shared items can't be split by seat as whole units; assign them to a seat or pay by items."))
		return [{"line_id": r["line_id"], "qty": r["qty"]} for r in rows]
	frappe.throw(_("Unknown split"))


def _payload(doc, part: dict, tenders: list | None, customer: str | None, service_charge_percent: float | None, tip: float):
	"""The invoice payload for one payment of a check: the chosen portions, their priced options, the
	service charge and the tip. Shared by the pre-payment quote and the payment itself, so the amount
	shown to the cashier is exactly the amount ERPNext will invoice."""
	unsent = [l.item_name for l in doc.lines if flt(l.sent_qty) < flt(l.qty) and not l.held]
	if unsent and doc.service_type == "Dine-in":
		frappe.throw(_("Send these to the kitchen before payment: {0}").format(", ".join(unsent)))
	portions = _portions(doc, part)
	by_id = {l.line_id: l for l in doc.lines}
	lines = []
	for p in portions:
		l = by_id[p["line_id"]]
		lines.append({"line_id": l.line_id, "item_code": l.item_code, "qty": str(p["qty"]), "note": l.note})
		for m in json.loads(l.modifiers or "[]"):
			if m.get("price_item"):
				lines.append({"line_id": f"{l.line_id}:{m['code']}", "item_code": m["price_item"], "qty": str(p["qty"])})
	settings = _settings()
	pct = flt(service_charge_percent if service_charge_percent is not None else settings.default_service_charge_percent)
	payload = {"lines": lines, "customer": customer, "tenders": tenders or [], "note": _("Table {0}").format(doc.table or doc.order_number)}
	if pct and settings.service_charge_item:
		base = sum(D(l["qty"]) * D(by_id[l["line_id"]].rate_preview) for l in lines if ":" not in l["line_id"])
		amount = splitting.service_charge(base, pct)
		payload["lines"].append({"line_id": "service", "item_code": settings.service_charge_item, "qty": "1", "rate_override": str(amount)})
	if flt(tip) > 0:
		if not settings.tip_item:
			frappe.throw(_("Set a tip item in Nest Restaurant Settings to record tips."))
		payload["lines"].append({"line_id": "tip", "item_code": settings.tip_item, "qty": "1", "rate_override": str(flt(tip))})
	return payload, portions, by_id, pct


def settle(name: str, register_name: str, part: dict, tenders: list, request_key: str, customer: str | None = None,
	service_charge_percent: float | None = None, tip: float = 0) -> dict:
	access.require("cashier", "supervisor", "manager")
	doc = orders._locked_order(name)
	if doc.register != register_name:
		frappe.throw(_("This check belongs to another register."), frappe.PermissionError)
	if doc.status not in ("Open", "Bill Requested", "Billed", "Partly Paid"):
		frappe.throw(_("This check can't be paid while {0}.").format(_(doc.status).lower()))
	payload, portions, by_id, pct = _payload(doc, part, tenders, customer, service_charge_percent, tip)
	settings = _settings()
	result = _submit_with_policy_lines(register_name, payload, request_key, doc)
	if result.get("status") != "posted":
		return result
	if result.get("replayed"):
		return {**result, "order": orders.view(name)}
	invoice = result["invoice"]
	for p in portions:
		by_id[p["line_id"]].paid_qty = flt(D(by_id[p["line_id"]].paid_qty) + D(p["qty"]))
	doc.append("invoices", {"invoice_doctype": invoice["doctype"], "invoice": invoice["name"], "amount": invoice["amount_due"],
		"split_label": part.get("label") or part.get("mode")})
	doc.paid_amount = flt(doc.paid_amount) + flt(invoice["amount_due"])
	doc.tip_amount = flt(doc.tip_amount) + flt(tip)
	doc.service_charge_percent = pct
	fully_paid = all(flt(l.paid_qty) >= flt(l.qty) for l in doc.lines)
	target = "Paid" if fully_paid else "Partly Paid"
	if doc.status in ("Open", "Bill Requested") and target in ("Paid", "Partly Paid"):
		orders._move_order(doc, "Billed")
	orders._move_order(doc, target)
	orders._save(doc)
	if fully_paid and doc.table:
		after = "Free" if settings.free_table_on == "Paid" else "Needs Cleaning"
		TABLE.assert_transition("Occupied", after)
		orders._move_table(doc.table, after)
	frappe.db.set_value(invoice["doctype"], invoice["name"], "nest_rest_order", doc.name, update_modified=False)
	audit.log("order.settle", ORDER, doc.name, register=register_name, invoice=invoice["name"], part=part)
	realtime.to_register(register_name, "paid", {"order": doc.name, "status": doc.status})
	return {**result, "order": orders.view(name)}


def quote(name: str, register_name: str, part: dict, customer: str | None = None, service_charge_percent: float | None = None, tip: float = 0) -> dict:
	"""What this payment will really cost: ERPNext builds the invoice (prices, taxes, service charge,
	priced options) without saving it."""
	access.require("cashier", "supervisor", "manager")
	doc = frappe.get_doc(ORDER, name)
	if doc.register != register_name:
		frappe.throw(_("This check belongs to another register."), frappe.PermissionError)
	payload, _portions_, by_id, pct = _payload(doc, part, None, customer, service_charge_percent, tip)
	frappe.flags.nest_policy_lines = {"service", "tip"}
	try:
		q = invoicing.quote(register_name, payload)
	finally:
		frappe.flags.nest_policy_lines = None
	service = sum(flt(l["amount"]) for l in q["lines"] if l["item_code"] == _settings().service_charge_item) if pct else 0
	return {
		"amount_due": flt(q["amount_due"]),
		"net_total": flt(q["net_total"]),
		"taxes": q["taxes"],
		"service_charge": service,
		"service_charge_percent": pct,
		"discount": flt(q["discount_amount"]),
		"currency": q["currency"],
	}


def _submit_with_policy_lines(register_name: str, payload: dict, request_key: str, order_doc) -> dict:
	"""Service charge and tip lines carry a rate set by policy or by the guest, not a staff price
	override, so they don't need a manager approval. Every other rate stays ERPNext's."""
	frappe.flags.nest_policy_lines = {"service", "tip"}
	try:
		return invoicing.submit(register_name, payload, request_key)
	finally:
		frappe.flags.nest_policy_lines = None


def remaining(name: str) -> dict:
	doc = frappe.get_doc(ORDER, name)
	access.require_register(doc.register)
	left = sum((D(l.qty) - D(l.paid_qty)) * D(l.rate_preview) for l in doc.lines)
	seats = sorted({cint(l.seat) for l in doc.lines if cint(l.seat) and flt(l.qty) > flt(l.paid_qty)})
	return {"order": name, "remaining_preview": str(left), "seats": seats, "equal_parts_hint": [str(x) for x in splitting.equal_parts(left, 2)] if left > Decimal(1) else []}
