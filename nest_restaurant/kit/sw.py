"""Serve this app's service workers at <route>/sw.js and <route>/customer/sw.js.

Frappe's StaticPage only serves binary files from www/, and website_route_rules map every
<route>/<path> to the SPA page, so a page_renderer hook answers exactly these two paths. Each worker's
scope is therefore its own route; the other Nest app's routes are never controlled by it.
"""

from __future__ import annotations

import os

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

from ..appspec import SPEC

WORKERS = {
	f"{SPEC.route}/sw.js": ("staff-sw.js", f"{SPEC.route}/"),
	f"{SPEC.route}/customer/sw.js": ("customer-sw.js", f"{SPEC.route}/customer/"),
}


class ServiceWorkerRenderer(BaseRenderer):
	def can_render(self):
		request = getattr(frappe.local, "request", None)
		return bool(request) and request.path in WORKERS

	def render(self):
		filename, scope = WORKERS[frappe.local.request.path]
		path = frappe.get_app_path(SPEC.app, "public", "frontend", filename)
		if not os.path.exists(path):
			return Response("// not built yet: run `bench build --app %s`\n" % SPEC.app, status=404, mimetype="application/javascript")
		with open(path, encoding="utf-8") as f:
			body = f.read()
		response = Response(body, mimetype="application/javascript")
		response.headers["Service-Worker-Allowed"] = scope
		response.headers["Cache-Control"] = "no-cache"  # browsers must always see a new worker version
		return response
