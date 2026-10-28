"""Cashier endpoints shared by Nest apps (vendored per app, whitelisted under the app's own path).
Thin: coerce input, authorise, call a service, return a plain dict."""

import frappe
from frappe import _

from ..appspec import SPEC
from ..core.fsm import MACHINES
from . import access, catalog, customers, invoicing, pins, register
from .util import obj


@frappe.whitelist()
def bootstrap() -> dict:
	access.require("cashier", "waiter", "kitchen", "supervisor", "manager")
	registers = []
	for name in access.assigned_registers() if not access.is_manager() else frappe.get_all(SPEC.dt("Register"), {"enabled": 1}, pluck="name"):
		reg = frappe.get_cached_doc(SPEC.dt("Register"), name)
		if not reg.enabled:
			continue
		profile = frappe.get_cached_doc("POS Profile", reg.pos_profile)
		session = register.open_session_for(name)
		registers.append(
			{
				"register": name,
				"company": reg.company,
				"pos_profile": reg.pos_profile,
				"currency": profile.currency,
				"invoice_mode": reg.invoice_mode,
				"blind_close": reg.blind_close,
				"customer_display": reg.customer_display,
				"receipt_printer": reg.receipt_printer,
				"outlet_label": reg.outlet_label,
				"payment_modes": [
					{"mode_of_payment": p.mode_of_payment, "default": p.default,
					 "type": frappe.get_cached_value("Mode of Payment", p.mode_of_payment, "type")}
					for p in profile.payments
				],
				"default_customer": profile.customer,
				"print_format": profile.print_format,
				"letter_head": profile.letter_head,
				"session": session.name if session else None,
			}
		)
	settings = frappe.get_cached_doc(SPEC.dt("Settings"))
	return {
		"user": frappe.session.user,
		"full_name": frappe.utils.get_fullname(frappe.session.user),
		"roles": {k: access.has_any(k) for k in SPEC.roles},
		"registers": registers,
		"settings": {
			"pricing_authority": settings.pricing_authority,
			"allow_offline_cash_sales": settings.allow_offline_cash_sales,
			"offline_max_hours": settings.offline_max_hours,
			"offline_max_sale_value": settings.offline_max_sale_value,
			"cash_rounding_increment": settings.cash_rounding_increment,
		},
		"return_reasons": frappe.get_all(SPEC.dt("Return Reason"), fields=["reason", "needs_approval"]),
		"machines": {k: m.as_dict() for k, m in MACHINES.items()},
	}


@frappe.whitelist()
def catalog_page(register_name: str, start: int = 0, since: str | None = None) -> dict:
	reg = access.require_register(register_name)
	return catalog.snapshot(reg.pos_profile, start=start, since=since)


@frappe.whitelist()
def promotions(register_name: str) -> list:
	reg = access.require_register(register_name)
	return invoicing.active_promotions(reg.pos_profile)


@frappe.whitelist()
def resolve_scan(register_name: str, code: str) -> dict:
	reg = access.require_register(register_name)
	return catalog.resolve_scan(reg.pos_profile, code)


@frappe.whitelist()
def search_customers(register_name: str, query: str = "") -> list:
	reg = access.require_register(register_name)
	return customers.search(frappe.get_cached_doc("POS Profile", reg.pos_profile), str(query)[:80])


@frappe.whitelist(methods=["POST"])
def open_register(register_name: str, floats=None) -> dict:
	return register.open_session(register_name, obj(floats, []))


@frappe.whitelist(methods=["POST"])
def cash_movement(register_name: str, direction: str, amount: float, reason: str, request_key: str, approval=None) -> dict:
	approver = None
	if direction == "Out" and not access.is_supervisor():
		approver = pins.consume_approval(obj(approval) or approval, action="cash_out")
	return register.add_cash_movement(register_name, direction, amount, reason, request_key, approved_by=approver)


@frappe.whitelist()
def shift_summary(register_name: str) -> dict:
	session = register.open_session_for(register_name)
	if not session:
		frappe.throw(_("No open shift on this register."))
	report = register.summary(session.name)
	report.pop("_expected_internal", None)
	return report


@frappe.whitelist(methods=["POST"])
def close_register(register_name: str, counts=None, reason: str = "", denominations=None) -> dict:
	return register.close_session(register_name, obj(counts), reason, obj(denominations) or None)


@frappe.whitelist(methods=["POST"])
def retry_close(session: str) -> dict:
	return register.retry_close(session)


@frappe.whitelist(methods=["POST"])
def quote(register_name: str, payload) -> dict:
	return invoicing.quote(register_name, obj(payload))


@frappe.whitelist(methods=["POST"])
def submit_sale(register_name: str, payload, request_key: str, source: str = "Online") -> dict:
	return invoicing.submit(register_name, obj(payload), request_key, source=source)


@frappe.whitelist()
def returnable(invoice_doctype: str, invoice: str) -> dict:
	access.require("cashier", "supervisor", "manager")
	return invoicing.returnable(invoice_doctype, invoice)


@frappe.whitelist(methods=["POST"])
def create_return(register_name: str, payload, request_key: str) -> dict:
	return invoicing.create_return(register_name, obj(payload), request_key)


@frappe.whitelist()
def recent_sales(register_name: str, query: str = "", limit: int = 30) -> list:
	session = register.open_session_for(register_name)
	access.require_register(register_name)
	dt = invoicing.invoice_doctype(session) if session else "Sales Invoice"
	filters = {SPEC.fld("session"): ["is", "set"], "docstatus": 1}
	if session and not access.is_supervisor():
		filters[SPEC.fld("session")] = session.name
	or_filters = {"name": ["like", f"%{query}%"], "customer_name": ["like", f"%{query}%"]} if query else None
	return frappe.get_list(
		dt,
		filters=filters,
		or_filters=or_filters,
		fields=["name", "customer_name", "grand_total", "rounded_total", "posting_date", "posting_time", "is_return", "currency"],
		order_by="creation desc",
		limit_page_length=min(int(limit or 30), 100),
	)


@frappe.whitelist(methods=["POST"])
def hold_cart(register_name: str, cart, label: str = "") -> dict:
	access.require_register(register_name)
	register.require_open_session(register_name)
	data = obj(cart)
	doc = frappe.get_doc(
		{
			"doctype": SPEC.dt("Held Cart"),
			"label": (label or "")[:80],
			"register": register_name,
			"held_by": frappe.session.user,
			"customer": data.get("customer"),
			"cart": frappe.as_json(data)[:200000],
			"total_preview": data.get("total_preview") or 0,
		}
	)
	doc.flags.ignore_permissions = True  # parked carts are scoped to the caller's own register
	doc.insert()
	return {"name": doc.name}


@frappe.whitelist()
def held_carts(register_name: str) -> list:
	access.require_register(register_name)
	return frappe.get_all(
		SPEC.dt("Held Cart"),
		filters={"register": register_name},
		fields=["name", "label", "held_by", "customer", "total_preview", "creation"],
		order_by="creation desc",
	)


@frappe.whitelist(methods=["POST"])
def resume_cart(name: str) -> dict:
	doc = frappe.get_doc(SPEC.dt("Held Cart"), name)
	access.require_register(doc.register)
	if doc.held_by != frappe.session.user and not access.is_supervisor():
		frappe.throw(_("This cart was held by someone else. Ask a supervisor."), frappe.PermissionError)
	cart = frappe.parse_json(doc.cart)
	frappe.delete_doc(SPEC.dt("Held Cart"), name, ignore_permissions=True)  # resumed exactly once
	return {"cart": cart}


@frappe.whitelist(methods=["POST"])
def set_pin(new_pin: str, current_pin: str | None = None) -> dict:
	pins.set_pin(new_pin, current_pin)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def request_approval(register_name: str, approver: str, pin: str, action: str, max_percent: float = 0) -> dict:
	return pins.request_approval(register_name, approver, pin, action, max_percent)


@frappe.whitelist(methods=["POST"])
def switch_user_check(user: str, pin: str) -> dict:
	"""Verify a colleague's PIN at a shared till; the browser then re-authenticates them normally.
	A PIN never creates a Frappe session on its own."""
	access.require("cashier", "supervisor", "manager")
	return {"ok": pins.verify(user, pin)}
