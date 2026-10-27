"""Integration-test fixtures shared by both apps (run with `bench --site <test-site> run-tests --app <app>`).

Builds on ERPNext's own `_Test Company` test records (loaded by erpnext.setup.utils.before_tests).
Every helper uses this app's SPEC names, so the same tests exercise `Nest POS …` or `Nest Restaurant …`.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

from ..appspec import SPEC
from ..core.fingerprint import new_key

COMPANY = "_Test Company"
WAREHOUSE = "_Test Warehouse - _TC"
CUSTOMER = "_Test Customer"


def ensure_user(email: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.add_roles(*roles, "Accounts User", "Stock User", "Sales User")
	return email


def make_profile(name: str) -> str:
	if frappe.db.exists("POS Profile", name):
		return name
	from erpnext.accounts.doctype.pos_profile.test_pos_profile import make_pos_profile

	profile = make_pos_profile(name=name, company=COMPANY, warehouse=WAREHOUSE)
	profile.customer = CUSTOMER
	profile.update_stock = 1
	profile.account_for_change_amount = frappe.db.get_value("Company", COMPANY, "default_cash_account") or "Cash - _TC"
	profile.save()
	return profile.name


def make_stock_item(code: str, rate: float, qty: float = 50, barcode: str | None = None) -> str:
	from erpnext.stock.doctype.item.test_item import make_item
	from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

	make_item(code, {"is_stock_item": 1, "stock_uom": "Nos", "valuation_rate": rate / 2}, barcode=barcode)
	price_list = frappe.db.get_value("POS Profile", {"company": COMPANY}, "selling_price_list") or "_Test Price List"
	if not frappe.db.exists("Item Price", {"item_code": code, "price_list": price_list}):
		frappe.get_doc({"doctype": "Item Price", "item_code": code, "price_list": price_list, "price_list_rate": rate}).insert()
	make_stock_entry(item_code=code, target=WAREHOUSE, qty=qty, basic_rate=rate / 2, company=COMPANY)
	return code


def make_register(name: str, profile: str, users: list[str], mode: str = "Direct") -> str:
	if frappe.db.exists(SPEC.dt("Register"), name):
		return name
	frappe.get_doc(
		{
			"doctype": SPEC.dt("Register"),
			"register_name": name,
			"company": COMPANY,
			"pos_profile": profile,
			"invoice_mode": mode,
			"outlet_label": f"{name} outlet",
			"users": [{"user": u, "can_open": 1} for u in users],
		}
	).insert(ignore_permissions=True)
	return name


def sale_payload(session: str, item: str, qty: float, cash: float, **extra) -> dict:
	return {"session": session, "lines": [{"line_id": "1", "item_code": item, "qty": qty}], "tenders": [{"mode_of_payment": "Cash", "amount": cash}], **extra}


def key(prefix: str = "test-") -> str:
	return new_key(prefix)


def gl_total(voucher_type: str, voucher_no: str) -> float:
	rows = frappe.get_all("GL Entry", {"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0}, ["debit", "credit"])
	return flt(sum(r.debit for r in rows) - sum(r.credit for r in rows), 2)
