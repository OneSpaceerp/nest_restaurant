"""Register, sale, return and security invariants shared by both apps.

Each app's tests/test_*.py imports `SharedFlows` and runs it against its own DocTypes. Review findings
are encoded as named regressions (see docs/verification.md for the mapping).
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, flt, now_datetime

from ..appspec import SPEC
from . import invoicing, register
from .requests import RequestConflict
from .testing import ensure_user, gl_total, key, make_profile, make_register, make_stock_item, sale_payload

CASHIER_A = f"cashier.a@{SPEC.field_prefix}.test"
CASHIER_B = f"cashier.b@{SPEC.field_prefix}.test"


class SharedSetup:
	"""Fixtures only (users, profile, stock item, register, an open shift for cashier A)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_user(CASHIER_A, [SPEC.role("cashier")])
		ensure_user(CASHIER_B, [SPEC.role("cashier")])
		cls.profile = make_profile(f"{SPEC.prefix} Test Profile")
		cls.item = make_stock_item(f"{SPEC.field_prefix.upper()}-TEST-ITEM", 100, qty=100, barcode=None)
		cls.register = make_register(f"{SPEC.prefix} Test Till", cls.profile, [CASHIER_A, CASHIER_B])
		frappe.db.commit()

	def setUp(self):
		frappe.set_user(CASHIER_A)
		self.session = register.open_session_for(self.register) or None
		if not self.session:
			register.open_session(self.register, [{"mode_of_payment": "Cash", "amount": 500}])
			self.session = register.open_session_for(self.register)

	def tearDown(self):
		frappe.set_user("Administrator")


class SharedFlows(SharedSetup):
	"""The shared invariant tests. Mix into exactly one IntegrationTestCase per app."""

	# ------------------------------------------------------------------ happy path + ledger
	def test_cash_sale_posts_native_invoice_with_ledgers(self):
		res = invoicing.submit(self.register, sale_payload(self.session.name, self.item, 2, 300), key())
		self.assertEqual(res["status"], "posted")
		inv = frappe.get_doc("Sales Invoice", res["invoice"]["name"])
		self.assertEqual(inv.docstatus, 1)
		self.assertEqual(inv.get(SPEC.fld("session")), self.session.name)
		self.assertEqual(flt(inv.change_amount), flt(300 - (inv.rounded_total or inv.grand_total)))
		self.assertEqual(gl_total("Sales Invoice", inv.name), 0.0, "GL must balance")
		self.assertTrue(frappe.db.exists("Stock Ledger Entry", {"voucher_no": inv.name, "is_cancelled": 0}))

	# ------------------------------------------------------------------ idempotency
	def test_retry_with_same_key_returns_the_same_invoice(self):
		k = key()
		first = invoicing.submit(self.register, sale_payload(self.session.name, self.item, 1, 200), k)
		again = invoicing.submit(self.register, sale_payload(self.session.name, self.item, 1, 200), k)
		self.assertEqual(first["invoice"]["name"], again["invoice"]["name"])
		self.assertEqual(frappe.db.count("Sales Invoice", {SPEC.fld("request"): first["request"]}), 1)

	def test_same_key_different_payload_is_rejected(self):
		k = key()
		invoicing.submit(self.register, sale_payload(self.session.name, self.item, 1, 200), k)
		with self.assertRaises(RequestConflict):
			invoicing.submit(self.register, sale_payload(self.session.name, self.item, 3, 400), k)

	# ------------------------------------------------------------------ review finding 1 (POSpire)
	def test_payload_cannot_choose_the_cashier(self):
		payload = sale_payload(self.session.name, self.item, 1, 200, owner_user=CASHIER_B, cashier=CASHIER_B)
		res = invoicing.submit(self.register, payload, key())
		req = frappe.get_doc(SPEC.dt("Sale Request"), res["request"])
		self.assertEqual(req.cashier, CASHIER_A)
		self.assertEqual(frappe.db.get_value("Sales Invoice", res["invoice"]["name"], "owner"), CASHIER_A)

	# ------------------------------------------------------------------ review finding 6 (EasyPOS shifts)
	def test_cannot_sell_on_another_cashiers_shift(self):
		frappe.set_user(CASHIER_B)
		with self.assertRaises(frappe.ValidationError):
			invoicing.submit(self.register, sale_payload(self.session.name, self.item, 1, 200), key())

	def test_closed_shift_rejects_sales(self):
		register.close_session(self.register, {"Cash": 500}, reason="test")
		with self.assertRaises(frappe.ValidationError):
			invoicing.submit(self.register, sale_payload(self.session.name, self.item, 1, 200), key())

	# ------------------------------------------------------------------ review finding 2 (EasyPOS payment proof)
	def test_gateway_tender_without_integration_is_refused(self):
		payload = sale_payload(self.session.name, self.item, 1, 0)
		payload["tenders"] = [{"mode_of_payment": "Cash", "amount": 120, "gateway": {"provider": "razorpay", "payment_id": "pay_forged"}}]
		with self.assertRaises(frappe.ValidationError):
			invoicing.submit(self.register, payload, key())

	# ------------------------------------------------------------------ provenance cannot be forged
	def test_invoice_shift_link_cannot_be_set_outside_the_till(self):
		frappe.set_user("Administrator")
		inv = frappe.new_doc("Sales Invoice")
		inv.update({"company": "_Test Company", "customer": "_Test Customer", SPEC.fld("session"): self.session.name})
		inv.append("items", {"item_code": self.item, "qty": 1, "rate": 100})
		with self.assertRaises(frappe.PermissionError):
			inv.insert()

	# ------------------------------------------------------------------ closing + offline review
	def test_close_records_expected_count_and_variance(self):
		invoicing.submit(self.register, sale_payload(self.session.name, self.item, 1, 200), key())
		report = register.summary(self.session.name)
		expected = flt(report["_expected_internal"]["Cash"])
		res = register.close_session(self.register, {"Cash": expected - 5}, reason="short by 5")
		self.assertEqual(flt(res["variance"]["Cash"]), -5.0)

	def test_late_offline_sale_is_kept_for_review_not_discarded(self):
		payload = sale_payload(self.session.name, self.item, 1, 200, client_created_at=str(add_to_date(now_datetime(), hours=-30)))
		res = invoicing.submit(self.register, payload, key(), source="Offline replay")
		self.assertEqual(res["status"], "needs_review")
		self.assertEqual(frappe.db.get_value(SPEC.dt("Sale Request"), res["request"], "status"), "Needs Review")

	# ------------------------------------------------------------------ returns
	def test_cumulative_over_return_is_blocked(self):
		sale = invoicing.submit(self.register, sale_payload(self.session.name, self.item, 2, 300), key())
		row = frappe.get_all("Sales Invoice Item", {"parent": sale["invoice"]["name"]}, pluck="name")[0]
		base = {"invoice_doctype": "Sales Invoice", "invoice": sale["invoice"]["name"], "reason": "Changed mind", "refund_mode": "Cash"}
		invoicing.create_return(self.register, {**base, "rows": {row: {"qty": 1}}}, key())
		invoicing.create_return(self.register, {**base, "rows": {row: {"qty": 1}}}, key())
		with self.assertRaises(frappe.ValidationError):
			invoicing.create_return(self.register, {**base, "rows": {row: {"qty": 1}}}, key())

	# ------------------------------------------------------------------ review finding 3 (generic dispatcher)
	def test_no_generic_document_method_dispatcher_is_exposed(self):
		import importlib
		import inspect
		import pkgutil

		api = importlib.import_module(f"{SPEC.app}.api")
		for mod in pkgutil.iter_modules(api.__path__):
			importlib.import_module(f"{SPEC.app}.api.{mod.name}")
		for fn in frappe.whitelisted:
			if not fn.__module__.startswith(SPEC.app):
				continue
			src = inspect.getsource(fn)
			self.assertNotIn("getattr(doc", src, f"{fn.__module__}.{fn.__name__} dispatches arbitrary methods")
			self.assertNotIn("run_method(method", src)
