"""Server-authoritative sales and returns on native ERPNext invoices.

The client sends item codes, quantities and tenders. Prices, taxes, promotions, totals, change and
stock come from ERPNext (and, in `nest` pricing mode, the Nest promotion engine). The browser's totals
are previews. ERPNext's own insert/submit posts every GL and stock ledger row.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from ..appspec import SPEC
from ..core import money
from ..core.fsm import SALE_REQUEST
from ..core.payloads import MAX_LINES, MAX_QTY, clean_note
from ..core.promotions import Context, Line, evaluate
from ..core.returns import SoldRow, plan_return
from . import access, audit, customers, pins, realtime, register, requests


class OfflinePolicyError(frappe.ValidationError):
	pass


def _settings():
	return frappe.get_cached_doc(SPEC.dt("Settings"))


def invoice_doctype(session) -> str:
	return "POS Invoice" if session.invoice_mode == "Consolidated" else "Sales Invoice"


# ------------------------------------------------------------------------------------------- build


def _clean_staff_lines(raw_lines) -> list[dict]:
	if not isinstance(raw_lines, list) or not raw_lines:
		frappe.throw(_("Add at least one item."))
	if len(raw_lines) > MAX_LINES:
		frappe.throw(_("A sale can hold up to {0} lines.").format(MAX_LINES))
	lines = []
	for i, raw in enumerate(raw_lines):
		item_code = str(raw.get("item_code") or "")
		item = frappe.get_cached_value(
			"Item", item_code, ["disabled", "is_sales_item", "has_variants", "has_serial_no", "has_batch_no"], as_dict=True
		)
		if not item or item.disabled or not item.is_sales_item or item.has_variants:
			frappe.throw(_("{0} cannot be sold. Choose an active, sellable item (not a template).").format(item_code))
		qty = money.D(raw.get("qty"))
		if qty <= 0 or qty > MAX_QTY:
			frappe.throw(_("Quantity for {0} is out of range.").format(item_code))
		line = {
			"line_id": str(raw.get("line_id") or i),
			"item_code": item_code,
			"qty": qty,
			"uom": raw.get("uom") or None,
			"serial_no": "\n".join(raw.get("serial_nos") or []) or None,
			"batch_no": raw.get("batch_no") or None,
			"note": clean_note(raw.get("note")),
			"rate_override": raw.get("rate_override"),
			"discount_percent": flt(raw.get("discount_percent")),
		}
		if item.has_serial_no and len((line["serial_no"] or "").split("\n")) != int(qty):
			frappe.throw(_("{0} needs one serial number per unit.").format(item_code))
		lines.append(line)
	return lines


def _resolve_customer(profile, customer: str | None) -> str:
	if customer:
		if not frappe.db.exists("Customer", customer):
			frappe.throw(_("Unknown customer"))
		# The POS Profile's customer groups decide, as in ERPNext's POS; cashiers rarely have Desk
		# permissions on Customer, and those should not decide who a till may sell to.
		if not customers.can_sell_to(profile, customer):
			frappe.throw(_("This register cannot sell to customer {0}.").format(customer), frappe.PermissionError)
		return customer
	if not profile.customer:
		frappe.throw(_("Set a default customer on POS Profile {0}.").format(profile.name))
	return profile.customer


def _authorise_overrides(lines: list[dict], bill_discount: float, approval: dict | None, register_name: str) -> str | None:
	"""Price overrides and manual discounts need a supervisor, or a manager PIN approval."""
	# Lines priced by policy (service charge, guest tip) are named by server code via frappe.flags,
	# which a client cannot set; every other rate change is a staff override.
	exempt = frappe.flags.get("nest_policy_lines") or set()
	lines = [l for l in lines if l["line_id"] not in exempt]
	wants = [l for l in lines if l["rate_override"] not in (None, "") or l["discount_percent"]] or bill_discount
	if not wants:
		return None
	largest = max([l["discount_percent"] for l in lines] + [flt(bill_discount)])
	if access.is_supervisor():
		approver = frappe.session.user
	else:
		approver = pins.consume_approval(approval, action="discount", max_percent=largest)
	audit.log(
		"price.override",
		register=register_name,
		approved_by=approver,
		lines=[{"item": l["item_code"], "rate": l["rate_override"], "pct": l["discount_percent"]} for l in lines],
		bill_discount=bill_discount,
	)
	return approver


def build(session, payload: dict):
	"""Return an unsaved invoice with ERPNext-computed totals (used by quote and submit)."""
	profile = frappe.get_cached_doc("POS Profile", session.pos_profile)
	lines = _clean_staff_lines(payload.get("lines"))
	settings = _settings()
	doctype = invoice_doctype(session)
	doc = frappe.new_doc(doctype)
	doc.update(
		{
			"company": session.company,
			"pos_profile": profile.name,
			"is_pos": 1,
			"customer": _resolve_customer(profile, payload.get("customer")),
			"posting_date": frappe.utils.nowdate(),
			"set_posting_time": 0,
			"update_stock": cint(profile.update_stock),
			"set_warehouse": profile.warehouse,
			"selling_price_list": profile.selling_price_list,
			"currency": profile.currency,
			"ignore_pricing_rule": 1 if settings.pricing_authority == "nest" else 0,
			"coupon_code": None,
			SPEC.fld("session"): session.name,
			"remarks": clean_note(payload.get("note")) or None,
		}
	)
	for l in lines:
		row = {
			"item_code": l["item_code"],
			"qty": flt(l["qty"]),
			"warehouse": profile.warehouse,
		}
		if l["uom"]:
			row["uom"] = l["uom"]
		if l["serial_no"] or l["batch_no"]:
			row.update({"use_serial_batch_fields": 1, "serial_no": l["serial_no"], "batch_no": l["batch_no"]})
		doc.append("items", row)
	doc.set_missing_values()
	_apply_pricing(doc, lines, payload, settings, session)
	bill_discount = flt(payload.get("bill_discount_percent"))
	if bill_discount:
		if bill_discount < 0 or bill_discount > 100:
			frappe.throw(_("Bill discount must be between 0 and 100 percent."))
		doc.apply_discount_on = "Grand Total"
		doc.additional_discount_percentage = bill_discount
	doc.calculate_taxes_and_totals()
	return doc, lines


def _apply_pricing(doc, lines, payload, settings, session) -> None:
	by_index = list(zip(doc.items, lines, strict=True))
	if settings.pricing_authority == "nest":
		promos = active_promotions(session.pos_profile)
		engine_lines = [
			Line(l["line_id"], row.item_code, money.D(row.qty), money.D(row.price_list_rate or row.rate), row.item_group or "", row.brand or "")
			for row, l in by_index
		]
		group = frappe.get_cached_value("Customer", doc.customer, "customer_group") or ""
		ctx = Context(at=now_datetime(), customer_group=group, profile=session.pos_profile, coupons=frozenset(payload.get("coupons") or []))
		result = evaluate(engine_lines, promos, ctx, doc.precision("rate", "items") or 2)
		if result.rejected_coupons:
			frappe.throw(_("Coupon not valid now: {0}").format(", ".join(result.rejected_coupons)))
		for row, l in by_index:
			off = result.line_discounts.get(l["line_id"])
			if off:
				base = flt(row.price_list_rate or row.rate)
				per_unit = flt(off / money.D(row.qty), row.precision("rate"))
				row.discount_amount = per_unit
				row.rate = base - per_unit
		doc.flags.nest_promotions = result.as_dict()
	for row, l in by_index:
		if l["rate_override"] not in (None, ""):
			rate = flt(l["rate_override"])
			if rate < 0:
				frappe.throw(_("A price cannot be negative."))
			row.rate = rate
			row.discount_amount = max(flt(row.price_list_rate) - rate, 0)
		elif l["discount_percent"]:
			if not 0 < l["discount_percent"] <= 100:
				frappe.throw(_("Discount must be between 0 and 100 percent."))
			row.discount_percentage = l["discount_percent"]
			row.rate = flt(row.price_list_rate * (1 - l["discount_percent"] / 100), row.precision("rate"))


def active_promotions(pos_profile: str) -> list[dict]:
	rows = frappe.get_all(SPEC.dt("Promotion"), filters={"disabled": 0}, pluck="name")
	out = []
	for name in rows:
		p = frappe.get_cached_doc(SPEC.dt("Promotion"), name)
		out.append(p.as_engine_dict())
	return [p for p in out if not p.get("profiles") or pos_profile in p["profiles"]]


def summarize(doc) -> dict:
	return {
		"doctype": doc.doctype,
		"name": doc.name if not doc.is_new() else None,
		"currency": doc.currency,
		"net_total": doc.net_total,
		"total_taxes_and_charges": doc.total_taxes_and_charges,
		"discount_amount": doc.discount_amount,
		"grand_total": doc.grand_total,
		"rounded_total": doc.rounded_total,
		"amount_due": doc.rounded_total or doc.grand_total,
		"paid_amount": doc.paid_amount,
		"change_amount": doc.change_amount,
		"lines": [
			{
				"item_code": r.item_code,
				"item_name": r.item_name,
				"qty": r.qty,
				"uom": r.uom,
				"price_list_rate": r.price_list_rate,
				"rate": r.rate,
				"amount": r.amount,
				"discount_amount": r.discount_amount,
			}
			for r in doc.items
		],
		"taxes": [{"description": t.description, "rate": t.rate, "amount": t.tax_amount} for t in doc.get("taxes") or []],
		"promotions": doc.flags.nest_promotions,
	}


def quote(register_name: str, payload: dict) -> dict:
	session = register.require_open_session(register_name, payload.get("session"))
	doc, _lines = build(session, payload)
	return summarize(doc)


# ------------------------------------------------------------------------------------------ submit


def _apply_tenders(doc, tenders: list[dict], allow_on_account: bool) -> dict:
	modes = {p.mode_of_payment: p for p in doc.payments}
	if not tenders:
		frappe.throw(_("At least one payment is required."))
	normalized = []
	for t in tenders:
		mop = t.get("mode_of_payment")
		if mop not in modes:
			frappe.throw(_("{0} is not accepted on this register.").format(mop))
		if t.get("gateway"):
			frappe.throw(
				_("Card-terminal and online payments need a configured payment integration on this register."),
				title=_("Payment integration required"),
			)
		normalized.append({"mode": mop, "amount": t.get("amount"), "allows_change": modes[mop].type == "Cash"})
	due = doc.rounded_total or doc.grand_total
	settled = money.settle_tenders(due, normalized, doc.precision("grand_total"))
	if settled["outstanding"] > 0 and not allow_on_account:
		frappe.throw(_("The payment doesn't cover the total."), title=_("Payment short"))
	used = {r["mode"]: r["amount"] for r in settled["rows"]}
	doc.set("payments", [p for p in doc.payments if p.mode_of_payment in used])
	for p in doc.payments:
		p.amount = flt(used[p.mode_of_payment])
		p.base_amount = flt(p.amount * flt(doc.conversion_rate or 1))
	doc.calculate_taxes_and_totals()
	if doc.doctype == "POS Invoice":
		doc.change_amount = flt(settled["change"])
		doc.base_change_amount = flt(settled["change"] * flt(doc.conversion_rate or 1))
	elif flt(doc.change_amount) != flt(settled["change"]):
		frappe.throw(_("Change could not be confirmed. Check the cash payment and try again."))
	if settled["change"] and not doc.account_for_change_amount:
		profile = frappe.get_cached_doc("POS Profile", doc.pos_profile)
		doc.account_for_change_amount = profile.account_for_change_amount or frappe.get_cached_value(
			"Company", doc.company, "default_cash_account"
		)
	return settled


def _check_offline_policy(payload: dict, doc, session) -> None:
	settings = _settings()
	if not cint(settings.allow_offline_cash_sales):
		raise OfflinePolicyError(_("Offline sales are switched off."))
	created = get_datetime(payload.get("client_created_at")) if payload.get("client_created_at") else None
	if not created:
		raise OfflinePolicyError(_("The offline sale has no creation time."))
	age_hours = (now_datetime() - created).total_seconds() / 3600
	if age_hours > cint(settings.offline_max_hours or 12) or age_hours < -0.25:
		raise OfflinePolicyError(_("The offline sale is outside the allowed offline window."))
	if flt(settings.offline_max_sale_value) and flt(doc.grand_total) > flt(settings.offline_max_sale_value):
		raise OfflinePolicyError(_("The offline sale is larger than the offline limit."))
	for p in doc.payments:
		if p.type != "Cash":
			raise OfflinePolicyError(_("Only cash can be taken offline."))
	if created < get_datetime(session.opened_at):
		raise OfflinePolicyError(_("The offline sale was made before this shift opened."))


def submit(register_name: str, payload: dict, request_key: str, source: str = "Online") -> dict:
	if source not in ("Online", "Offline replay"):
		frappe.throw(_("Unknown source"))
	session = register.require_open_session(register_name, payload.get("session"))
	req_values = {
		"kind": "Sale",
		"status": "Received",
		"source": source,
		"session": session.name,
		"cashier": frappe.session.user,
		"client_created_at": get_datetime(payload["client_created_at"]) if payload.get("client_created_at") else None,
	}
	outcome, req_name = requests.begin(SPEC.dt("Sale Request"), request_key, payload, req_values)
	if outcome == "replay":
		return _stored_result(req_name)

	frappe.db.savepoint("nest_sale")
	try:
		doc, lines = build(session, payload)
		approver = _authorise_overrides(lines, flt(payload.get("bill_discount_percent")), payload.get("approval"), register_name)
		settled = _apply_tenders(doc, payload.get("tenders") or [], allow_on_account=bool(payload.get("on_account")) and access.is_supervisor())
		if source == "Offline replay":
			_check_offline_policy(payload, doc, session)
		doc.set(SPEC.fld("request"), req_name)
		doc.flags.nest_app = SPEC.app
		doc.insert()
		doc.submit()
	except (OfflinePolicyError, frappe.ValidationError) as e:
		if source != "Offline replay":
			raise
		# A sale the customer already paid for offline is never discarded: it waits for a manager.
		frappe.db.rollback(save_point="nest_sale")
		_mark(req_name, "Needs Review", error=str(e))
		realtime.to_register(register_name, "review", {"request": req_name})
		return {"status": "needs_review", "request": req_name, "message": str(e)}

	_mark(req_name, "Posted", invoice=doc)
	if approver:
		audit.log("sale.approved_override", doc.doctype, doc.name, register=register_name, approved_by=approver)
	realtime.to_register(register_name, "sale", {"invoice": doc.name, "session": session.name})
	return {"status": "posted", "request": req_name, "invoice": summarize(doc), "change": str(settled["change"])}


def _mark(req_name: str, status: str, invoice=None, error: str | None = None) -> None:
	req = frappe.get_doc(SPEC.dt("Sale Request"), req_name)
	SALE_REQUEST.assert_transition(req.status, status)
	req.status = status
	if invoice is not None:
		req.invoice_doctype = invoice.doctype
		req.invoice = invoice.name
	if error:
		req.error = error[:1000]
	req.flags.ignore_permissions = True  # ledger bookkeeping for a request the caller already owns
	req.save()


def _stored_result(req_name: str) -> dict:
	req = frappe.get_doc(SPEC.dt("Sale Request"), req_name)
	if req.cashier != frappe.session.user and not access.is_supervisor():
		frappe.throw(_("This request belongs to another cashier."), frappe.PermissionError)
	if req.status == "Posted":
		inv = frappe.get_doc(req.invoice_doctype, req.invoice)
		return {"status": "posted", "request": req.name, "invoice": summarize(inv), "replayed": True}
	return {"status": frappe.scrub(req.status), "request": req.name, "message": req.error, "replayed": True}


# ----------------------------------------------------------------------------------------- returns


def _returned_quantities(doctype: str, original: str) -> tuple[dict, dict]:
	link = "pos_invoice_item" if doctype == "POS Invoice" else "sales_invoice_item"
	item_dt = f"{doctype} Item"
	rows = frappe.db.sql(
		f"""select ri.{link} as row_id, abs(ri.qty) as qty, ri.serial_no
		from `tab{item_dt}` ri join `tab{doctype}` r on r.name = ri.parent
		where r.return_against = %s and r.docstatus = 1 and r.is_return = 1""",
		original,
		as_dict=True,
	)
	qty: dict[str, Decimal] = {}
	serials: dict[str, list[str]] = {}
	for r in rows:
		qty[r.row_id] = qty.get(r.row_id, Decimal(0)) + money.D(r.qty)
		serials.setdefault(r.row_id, []).extend((r.serial_no or "").split())
	return qty, serials


def returnable(invoice_doctype_: str, invoice: str) -> dict:
	if invoice_doctype_ not in ("Sales Invoice", "POS Invoice"):
		frappe.throw(_("Unknown invoice type"))
	doc = frappe.get_doc(invoice_doctype_, invoice)
	doc.check_permission("read")
	if doc.docstatus != 1 or doc.is_return:
		frappe.throw(_("Only a submitted sale can be returned."))
	qty, serials = _returned_quantities(doc.doctype, doc.name)
	return {
		"invoice": doc.name,
		"customer": doc.customer,
		"rows": [
			{
				"row_id": r.name,
				"item_code": r.item_code,
				"item_name": r.item_name,
				"qty": r.qty,
				"returned_qty": str(qty.get(r.name, 0)),
				"net_unit": flt(r.net_amount / r.qty) if r.qty else 0,
				"serial_nos": (r.serial_no or "").split(),
				"returned_serials": serials.get(r.name, []),
			}
			for r in doc.items
		],
	}


def create_return(register_name: str, payload: dict, request_key: str) -> dict:
	session = register.require_open_session(register_name, payload.get("session"))
	reason = (payload.get("reason") or "").strip()
	if not reason or not frappe.db.exists(SPEC.dt("Return Reason"), reason):
		frappe.throw(_("Choose a return reason."))
	reason_doc = frappe.get_cached_doc(SPEC.dt("Return Reason"), reason)
	original_dt = payload.get("invoice_doctype") or invoice_doctype(session)
	original = frappe.get_doc(original_dt, payload.get("invoice"))
	original.check_permission("read")
	if original.company != session.company:
		frappe.throw(_("That sale belongs to another company."), frappe.PermissionError)
	if not original.get(SPEC.fld("session")) and not access.is_supervisor():
		frappe.throw(_("Only a supervisor can return a sale made outside this app."), frappe.PermissionError)
	outcome, req_name = requests.begin(
		SPEC.dt("Sale Request"),
		request_key,
		payload,
		{"kind": "Return", "status": "Received", "source": "Online", "session": session.name, "cashier": frappe.session.user},
	)
	if outcome == "replay":
		return _stored_result(req_name)

	approver = None
	if reason_doc.needs_approval and not access.is_supervisor():
		approver = pins.consume_approval(payload.get("approval"), action="refund")

	qty, serials = _returned_quantities(original.doctype, original.name)
	sold = [
		SoldRow(r.name, r.item_code, money.D(r.qty), money.D(r.net_amount), qty.get(r.name, Decimal(0)),
			tuple((r.serial_no or "").split()), tuple(serials.get(r.name, [])))
		for r in original.items
	]
	plan = plan_return(sold, payload.get("rows") or {}, original.precision("grand_total"))

	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	ret = make_return_doc(original.doctype, original.name)
	link = "pos_invoice_item" if original.doctype == "POS Invoice" else "sales_invoice_item"
	wanted = {p["row_id"]: p for p in plan}
	ret.set("items", [i for i in ret.items if i.get(link) in wanted])
	for i in ret.items:
		p = wanted[i.get(link)]
		i.qty = -flt(p["qty"])
		if p["serial_nos"]:
			i.use_serial_batch_fields = 1
			i.serial_no = "\n".join(p["serial_nos"])
		if not reason_doc.restock:
			ret.update_stock = 0
	ret.set(SPEC.fld("session"), session.name)
	ret.set(SPEC.fld("request"), req_name)
	ret.remarks = _("Return reason: {0}").format(reason)
	ret.calculate_taxes_and_totals()
	refund_mode = payload.get("refund_mode")
	modes = {p.mode_of_payment for p in ret.payments} or {refund_mode}
	if refund_mode not in modes:
		frappe.throw(_("{0} can't be used for refunds here.").format(refund_mode))
	ret.set("payments", [p for p in ret.payments if p.mode_of_payment == refund_mode])
	for p in ret.payments:
		p.amount = flt(ret.rounded_total or ret.grand_total)
	ret.calculate_taxes_and_totals()
	ret.flags.nest_app = SPEC.app
	ret.insert()
	ret.submit()
	_mark(req_name, "Posted", invoice=ret)
	audit.log("sale.return", ret.doctype, ret.name, register=register_name, approved_by=approver, against=original.name, reason=reason)
	return {"status": "posted", "request": req_name, "invoice": summarize(ret)}
