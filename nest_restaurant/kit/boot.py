"""Boot payloads rendered into the PWA shells by www/ controllers. No secrets: this HTML can be cached
by the browser and the service worker."""

from __future__ import annotations

import frappe
from frappe.boot import load_translations

from ..appspec import SPEC


def staff_context(context, route: str):
	# Signed-out visitors get the same shell with user "Guest": the app shows its own sign-in screen
	# (NLogin.vue) instead of Frappe's /login, and the boot carries nothing a guest should not see.
	# Shopper (website) accounts have no business in the staff app: send them to the shopper app.
	if frappe.session.user != "Guest" and frappe.db.get_value("User", frappe.session.user, "user_type") == "Website User":
		frappe.local.flags.redirect_location = f"{route}/customer/"
		raise frappe.Redirect
	csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()  # persist the freshly minted token before the page uses it  # nosemgrep
	return _context(csrf_token, route, "staff")


def customer_context(context, route: str, extra: dict | None = None):
	csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()  # nosemgrep
	return _context(csrf_token, route, "customer", extra)


def _context(csrf_token: str, route: str, surface: str, extra: dict | None = None):
	boot = frappe._dict(
		{
			"site_name": frappe.local.site,
			"app": SPEC.app,
			"surface": surface,
			"route": route,
			"socketio_port": frappe.conf.get("socketio_port") or 9000,
			"user": frappe.session.user if surface == "staff" else "Guest",
			"lang": frappe.local.lang,
			"rtl": frappe.local.lang in ("ar", "he", "fa", "ur"),
		}
	)
	boot.update(extra or {})
	load_translations(boot)
	ctx = frappe._dict()
	ctx.csrf_token = csrf_token
	ctx.boot = frappe.as_json(boot)
	ctx.no_cache = 1
	return ctx
