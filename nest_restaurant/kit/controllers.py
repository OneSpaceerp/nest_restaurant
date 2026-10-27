"""Base controllers for the kit DocTypes. Status fields only move along the declared state machines,
whoever saves the document (API, Desk, import)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from ..appspec import SPEC
from ..core.fsm import REGISTER_SESSION, SALE_REQUEST
from ..core.tokens import new_token


class SettingsController(Document):
	def validate(self):
		if not self.signing_secret:
			self.signing_secret = new_token(48)
		if cint(self.offline_max_hours) < 0 or cint(self.offline_max_hours) > 72:
			frappe.throw(_("Offline sales can be allowed for 0 to 72 hours."))


class RegisterController(Document):
	def validate(self):
		profile = frappe.get_cached_doc("POS Profile", self.pos_profile)
		if profile.company != self.company:
			frappe.throw(_("The POS Profile belongs to {0}, not {1}.").format(profile.company, self.company))
		if not profile.payments:
			frappe.throw(_("Add at least one payment method to POS Profile {0}.").format(self.pos_profile))
		seen = set()
		for row in self.users or []:
			if row.user in seen:
				frappe.throw(_("{0} is listed twice.").format(row.user))
			seen.add(row.user)
		if self.invoice_mode == "Consolidated":
			others = frappe.get_all(
				self.doctype,
				{"pos_profile": self.pos_profile, "name": ["!=", self.name or ""], "invoice_mode": "Consolidated"},
				pluck="name",
			)
			if others:
				frappe.throw(
					_("POS Profile {0} is already used by consolidated register {1}. ERPNext allows one open shift per profile in that mode.").format(
						self.pos_profile, others[0]
					)
				)
		if not self.is_new() and self.has_value_changed("invoice_mode"):
			if frappe.db.exists(SPEC.dt("Register Session"), {"register": self.name, "status": ["!=", "Closed"]}):
				frappe.throw(_("Close every shift on this register before changing its invoice mode."))


class RegisterSessionController(Document):
	def validate(self):
		before = self.get_doc_before_save()
		REGISTER_SESSION.assert_transition(before.status if before else None, self.status)
		if before:
			for field in ("register", "cashier", "invoice_mode", "pos_profile", "company"):
				if self.has_value_changed(field):
					frappe.throw(_("{0} cannot change after opening.").format(field))
		self.version = cint(self.version) + 1

	def on_trash(self):
		frappe.throw(_("Register sessions are kept for audit and cannot be deleted."))


class SaleRequestController(Document):
	def validate(self):
		before = self.get_doc_before_save()
		SALE_REQUEST.assert_transition(before.status if before else None, self.status)

	def on_trash(self):
		frappe.throw(_("Sale requests are kept for audit and cannot be deleted."))


class StaffPINController(Document):
	def validate(self):
		if self.has_value_changed("pin_hash") and self.pin_hash and not self.pin_hash.startswith("pbkdf2_sha256$"):
			frappe.throw(_("PINs are set from the till, never typed here."))


class AppendOnlyController(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(_("{0} entries cannot be edited.").format(_(self.doctype)))

	def on_trash(self):
		frappe.throw(_("{0} entries are kept for audit.").format(_(self.doctype)))


class PromotionController(Document):
	def validate(self):
		from ..core.promotions import KINDS

		if self.kind not in KINDS:
			frappe.throw(_("Unknown promotion kind"))
		if self.kind == "bxgy" and (cint(self.buy_qty) < 1 or cint(self.get_qty) < 1):
			frappe.throw(_("Buy and get quantities must be at least 1."))
		if self.kind == "bundle" and not self.bundle_items:
			frappe.throw(_("Add the bundle's items."))
		if self.kind == "spend_save" and (not self.threshold or not self.discount_amount):
			frappe.throw(_("Set the spend threshold and the amount saved."))
		if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
			frappe.throw(_("The promotion ends before it starts."))
		if self.coupon_code:
			self.coupon_code = self.coupon_code.strip().upper()

	def as_engine_dict(self) -> dict:
		scope = {"items": [], "item_groups": [], "brands": []}
		key = {"Item": "items", "Item Group": "item_groups", "Brand": "brands"}
		for row in self.scope or []:
			scope[key[row.scope_type]].append(row.value)
		lines = lambda text: [x.strip() for x in (text or "").splitlines() if x.strip()]  # noqa: E731
		days = [int(d) for d in (self.days_of_week or "").replace(" ", "").split(",") if d.isdigit()]
		return {
			"name": self.name,
			"kind": self.kind,
			"disabled": self.disabled,
			"priority": self.priority,
			"exclusive": self.exclusive,
			"stackable": self.stackable,
			"value": self.value,
			"buy_qty": self.buy_qty,
			"get_qty": self.get_qty,
			"get_discount_percent": self.get_discount_percent,
			"threshold": self.threshold,
			"discount_amount": self.discount_amount,
			"repeat": self.repeat,
			"bundle_price": self.bundle_price,
			"bundle_items": [{"item_code": b.item_code, "qty": b.qty} for b in self.bundle_items or []],
			"valid_from": str(self.valid_from) if self.valid_from else None,
			"valid_to": str(self.valid_to) if self.valid_to else None,
			"days_of_week": days,
			"time_from": str(self.time_from) if self.time_from else None,
			"time_to": str(self.time_to) if self.time_to else None,
			"coupon_code": self.coupon_code,
			"customer_groups": lines(self.customer_groups),
			"profiles": lines(self.profiles),
			"min_qty": self.min_qty,
			"min_amount": self.min_amount,
			"max_applications": self.max_applications,
			"applies_to": scope,
		}
