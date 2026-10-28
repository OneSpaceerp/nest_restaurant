# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Guest self-ordering from a table QR.

The QR carries a signed table context; scanning it starts a visit-scoped guest session (only the
token's hash is stored). A guest joining a table that already has an open check must enter that
check's visit code, so nobody can attach to another party's bill from a photo of the QR.

In the default "Direct to kitchen" mode one accepted submission becomes order lines, kitchen tickets
for the right stations and a cashier notification, all in one transaction — no re-entry by staff.
"""

from __future__ import annotations

import hmac
import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, now_datetime

from nest_restaurant.core.fingerprint import classify_replay, fingerprint, validate_key
from nest_restaurant.core.fsm import GUEST_SUBMISSION
from nest_restaurant.core.payloads import clean_lines
from nest_restaurant.core.tokens import TokenError, hash_token, new_token, verify_context
from nest_restaurant.kit import access, catalog, realtime
from nest_restaurant.services import orders

SESSION = "Nest Restaurant Guest Session"
SUBMISSION = "Nest Restaurant Guest Submission"
SERVICE_REQUEST = "Nest Restaurant Service Request"
MAX_CONFIRM_ATTEMPTS = 5
MAX_SUBMISSIONS = 30


def _settings():
	return frappe.get_cached_doc("Nest Restaurant Settings")


def start_visit(code: str) -> dict:
	settings = _settings()
	if settings.guest_ordering_mode == "Off":
		frappe.throw(_("Ordering from the table is not available here. Please ask your server."), frappe.PermissionError)
	try:
		ctx = verify_context(settings.get_password("signing_secret"), code, "table")
	except TokenError as e:
		frappe.throw(_("This table code isn't valid ({0}). Ask your server for help.").format(e), frappe.PermissionError)
	table = frappe.db.get_value("Nest Restaurant Table", ctx.get("table"), ["name", "register", "table_label", "guest_ordering", "current_order", "status"], as_dict=True)
	if not table or table.register != ctx.get("register") or not table.guest_ordering or table.status == "Out of Service":
		frappe.throw(_("This table isn't taking orders from the QR code."), frappe.PermissionError)
	order = table.current_order if table.current_order and frappe.db.get_value(orders.ORDER, table.current_order, "status") in orders.EDITABLE else None
	token = new_token()
	doc = frappe.get_doc(
		{
			"doctype": SESSION,
			"token_hash": hash_token(token),
			"register": table.register,
			"table": table.name,
			"order": order,
			"service_type": "Dine-in",
			"status": "Active",
			"confirmed": 0 if order else 1,
			"expires_at": add_to_date(now_datetime(), minutes=cint(settings.guest_session_minutes) or 90),
			"last_seen": now_datetime(),
		}
	)
	doc.flags.ignore_permissions = True  # guest visit record; only the token hash is stored
	doc.insert()
	frappe.db.commit()  # the next request must find this session  # nosemgrep
	return {
		"token": token,
		"table_label": table.table_label,
		"needs_visit_code": bool(order),
		"outlet": frappe.db.get_value("Nest Restaurant Register", table.register, "outlet_label") or "",
		"mode": settings.guest_ordering_mode,
	}


def _session(token: str, need_confirmed: bool = True):
	try:
		h = hash_token(token or "")
	except TokenError:
		frappe.throw(_("Please scan the table code again."), frappe.PermissionError)
	name = frappe.db.get_value(SESSION, {"token_hash": h, "status": "Active"}, "name", for_update=True)
	if not name:
		frappe.throw(_("Please scan the table code again."), frappe.PermissionError)
	doc = frappe.get_doc(SESSION, name)
	if doc.expires_at < now_datetime():
		frappe.db.set_value(SESSION, name, "status", "Expired")
		frappe.throw(_("Your table session timed out. Please scan the table code again."), frappe.PermissionError)
	if doc.order and frappe.db.get_value(orders.ORDER, doc.order, "status") in ("Paid", "Cancelled", "Merged"):
		frappe.db.set_value(SESSION, name, "status", "Expired")
		frappe.throw(_("This visit has ended. Scan the table code to start a new one."), frappe.PermissionError)
	if need_confirmed and not doc.confirmed:
		frappe.throw(_("Enter the visit code shown on your table's bill or ask your server."), frappe.PermissionError)
	minutes = cint(_settings().guest_session_minutes) or 90
	frappe.db.set_value(SESSION, name, {"expires_at": add_to_date(now_datetime(), minutes=minutes), "last_seen": now_datetime()}, update_modified=False)
	return doc


def confirm(token: str, visit_code: str) -> dict:
	doc = _session(token, need_confirmed=False)
	if doc.confirmed:
		return {"confirmed": True}
	expected = frappe.db.get_value(orders.ORDER, doc.order, "visit_code") or ""
	if expected and hmac.compare_digest(expected, (visit_code or "").strip()):
		frappe.db.set_value(SESSION, doc.name, "confirmed", 1)
		return {"confirmed": True}
	attempts = cint(frappe.cache.incr(f"nest_rest:visit_attempts:{doc.name}"))
	if attempts >= MAX_CONFIRM_ATTEMPTS:
		frappe.db.set_value(SESSION, doc.name, "status", "Revoked")
		frappe.db.commit()  # keep the revocation even though this request reports an error  # nosemgrep
		frappe.throw(_("Too many wrong codes. Please ask your server."), frappe.PermissionError)
	frappe.throw(_("That code doesn't match this table's bill."))


def menu(token: str) -> dict:
	doc = _session(token, need_confirmed=False)
	out = menu_for_register(doc.register, guest_only=True)
	out["table_label"] = frappe.db.get_value("Nest Restaurant Table", doc.table, "table_label")
	out["needs_visit_code"] = not doc.confirmed
	return out


def menu_for_register(register: str, guest_only: bool) -> dict:
	"""Menu sections with prices from the register's price list and option groups. Shared by the guest
	menu and the waiter/cashier order screen; guests only see items marked for the guest menu."""
	reg = frappe.get_cached_doc("Nest Restaurant Register", register)
	price_list = frappe.get_cached_value("POS Profile", reg.pos_profile, "selling_price_list")
	filters = {"register": register}
	if guest_only:
		filters["guest_visible"] = 1
	rows = frappe.get_all(
		"Nest Restaurant Menu Item",
		filters,
		["name", "item_code", "display_name", "display_name_ar", "section", "sequence", "sold_out", "description", "allergens", "dietary", "image", "default_course"],
		order_by="section asc, sequence asc",
	)
	prices = catalog._price_map(price_list, [r.item_code for r in rows])
	# a dish without its own menu photo shows the ERPNext Item's image
	item_images = dict(
		frappe.get_all("Item", {"name": ["in", [r.item_code for r in rows] or ["__none__"]]}, ["name", "image"], as_list=True)
	)
	sections: dict[str, list] = {}
	for r in rows:
		if not prices.get(r.item_code):
			continue
		groups = []
		for g in frappe.get_all("Nest Restaurant Menu Item Modifier", {"parent": r.name}, pluck="modifier_group"):
			grp = frappe.get_cached_doc("Nest Restaurant Modifier Group", g)
			opt_prices = catalog._price_map(price_list, [o.price_item for o in grp.options if o.price_item])
			opt_images = dict(
				frappe.get_all("Item", {"name": ["in", [o.price_item for o in grp.options if o.price_item] or ["__none__"]]}, ["name", "image"], as_list=True)
			)
			groups.append(
				{
					"group": grp.group_name,
					"min": cint(grp.min_select),
					"max": cint(grp.max_select),
					"options": [
						{"code": o.option_code, "name": o.option_name, "description": o.get("description"),
						 "image": o.get("image") or opt_images.get(o.price_item), "sold_out": bool(o.sold_out),
						 "price": (opt_prices.get(o.price_item) or {}).get("rate") if o.price_item else 0}
						for o in grp.options
					],
				}
			)
		sections.setdefault(r.section or _("Menu"), []).append(
			{
				"item_code": r.item_code,
				"name": r.display_name or r.item_code,
				"name_ar": r.display_name_ar,
				"description": r.description,
				"allergens": [a.strip() for a in (r.allergens or "").split(",") if a.strip()],
				"dietary": [a.strip() for a in (r.dietary or "").split(",") if a.strip()],
				"image": r.image or item_images.get(r.item_code),
				"price": prices[r.item_code]["rate"],
				"sold_out": bool(r.sold_out),
				"course": cint(r.default_course) or 1,
				"options": groups,
			}
		)
	# sections in the order set in the menu builder (Menu Section); any others follow by name
	order = {
		s.section_name: (i, s.section_name_ar)
		for i, s in enumerate(
			frappe.get_all("Nest Restaurant Menu Section", {"register": register}, ["section_name", "section_name_ar"], order_by="sequence asc, section_name asc")
		)
	}
	names = sorted(sections, key=lambda k: (order.get(k, (len(order), None))[0], k))
	return {
		"currency": frappe.get_cached_value("POS Profile", reg.pos_profile, "currency"),
		"sections": [{"name": k, "name_ar": order.get(k, (0, None))[1], "items": sections[k]} for k in names],
	}


def submit(token: str, raw_lines, request_key: str) -> dict:
	settings = _settings()
	doc = _session(token)
	key = validate_key(request_key)
	payload = {"lines": raw_lines}
	fp = fingerprint(payload)
	existing = frappe.db.get_value(SUBMISSION, {"request_key": key}, ["name", "fingerprint", "guest_session", "status", "order"], as_dict=True)
	if existing:
		if existing.guest_session != doc.name or classify_replay(existing.fingerprint, fp) == "conflict":
			frappe.throw(_("This order was already sent with different items."))
		return {"submission": existing.name, "status": existing.status, "order": existing.order, "replayed": True}
	if cint(doc.submissions) >= MAX_SUBMISSIONS:
		frappe.throw(_("Please ask your server to add more items."))
	menu_items = {k: v for k, v in orders.menu_index(doc.register).items() if v.guest_visible}
	clean_lines(raw_lines, set(menu_items))  # validate early for a precise message
	order = doc.order
	if not order:
		opened = orders.open_order(doc.register, doc.table, 0, "Dine-in", f"{key}:open", actor="Guest")
		order = opened["order"]
		frappe.db.set_value(SESSION, doc.name, "order", order)
	direct = settings.guest_ordering_mode == "Direct to kitchen"
	sub = frappe.get_doc(
		{
			"doctype": SUBMISSION,
			"guest_session": doc.name,
			"order": order,
			"request_key": key,
			"fingerprint": fp,
			"status": "Received",
			"payload": json.dumps(raw_lines, default=str)[:20000],
		}
	)
	sub.flags.ignore_permissions = True
	sub.insert()
	frappe.db.set_value(SESSION, doc.name, "submissions", cint(doc.submissions) + 1)
	register = doc.register
	if direct:
		_accept(sub, actor="Guest")
		realtime.to_register(register, "guest_order", {"order": order, "submission": sub.name, "status": "Accepted"})
	else:
		_move(sub, "Awaiting Approval")
		realtime.to_register(register, "guest_order", {"order": order, "submission": sub.name, "status": "Awaiting Approval"})
	return {"submission": sub.name, "status": sub.status, "order": order}


def _move(sub, target: str, **values) -> None:
	GUEST_SUBMISSION.assert_transition(sub.status, target)
	sub.status = target
	sub.update(values)
	sub.flags.ignore_permissions = True
	sub.save()


def _accept(sub, actor: str) -> None:
	raw = json.loads(sub.payload)
	orders.add_lines(sub.order, raw, f"{sub.request_key}:add", source="Guest", actor=actor, guest_only=True)
	orders.send(sub.order, f"{sub.request_key}:send", actor=actor)
	_move(sub, "Accepted", decided_by=None if actor == "Guest" else actor)


def decide(submission: str, accept: bool, reason: str = "") -> dict:
	"""Staff approval in "Cashier approves first" mode."""
	frappe.db.get_value(SUBMISSION, submission, "name", for_update=True)
	sub = frappe.get_doc(SUBMISSION, submission)
	order_register = frappe.db.get_value(orders.ORDER, sub.order, "register")
	access.require("cashier", "waiter", "supervisor", "manager")
	access.require_register(order_register)
	if sub.status != "Awaiting Approval":
		return {"submission": sub.name, "status": sub.status}
	if accept:
		_accept(sub, actor=frappe.session.user)
	else:
		_move(sub, "Rejected", decided_by=frappe.session.user, reject_reason=(reason or "")[:200])
	realtime.to_register(order_register, "guest_order", {"order": sub.order, "submission": sub.name, "status": sub.status})
	return {"submission": sub.name, "status": sub.status}


def status(token: str) -> dict:
	doc = _session(token, need_confirmed=False)
	subs = frappe.get_all(SUBMISSION, {"guest_session": doc.name}, ["name", "status", "creation", "reject_reason"], order_by="creation asc")
	out = {"table_label": frappe.db.get_value("Nest Restaurant Table", doc.table, "table_label"), "submissions": subs, "order": None}
	if doc.order and doc.confirmed:
		view = orders.view(doc.order, for_guest=True)
		out["order"] = {k: view[k] for k in ("status", "order_number", "subtotal_preview", "paid_amount", "lines")}
	return out


def service_request(token: str, request_type: str) -> dict:
	doc = _session(token)
	if request_type not in ("Bill", "Waiter", "Water", "Cutlery"):
		frappe.throw(_("Unknown request"))
	if not doc.order:
		frappe.throw(_("Order something first, or ask your server."))
	if frappe.db.exists(SERVICE_REQUEST, {"order": doc.order, "request_type": request_type, "status": "Open"}):
		return {"status": "already_requested"}
	req = frappe.get_doc({"doctype": SERVICE_REQUEST, "order": doc.order, "table": doc.table, "request_type": request_type, "status": "Open"})
	req.flags.ignore_permissions = True
	req.insert()
	if request_type == "Bill":
		orders.request_bill(doc.order, actor="Guest")
	realtime.to_register(doc.register, "service_request", {"order": doc.order, "table": doc.table, "type": request_type})
	return {"status": "requested"}


def resolve_service_request(name: str) -> dict:
	req = frappe.get_doc(SERVICE_REQUEST, name)
	access.require("cashier", "waiter", "supervisor", "manager")
	access.require_register(frappe.db.get_value(orders.ORDER, req.order, "register"))
	req.status = "Done"
	req.done_by = frappe.session.user
	req.flags.ignore_permissions = True
	req.save()
	return {"name": req.name, "status": "Done"}
