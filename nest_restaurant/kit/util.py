"""Request-shape helpers for whitelisted endpoints."""
import json

import frappe
from frappe import _

MAX_BODY = 256 * 1024


def obj(value, default=None):
	"""Accept a dict or a JSON string from the client; bound the size; reject other shapes."""
	if value is None or value == "":
		return {} if default is None else default
	if isinstance(value, (dict, list)):
		return value
	if isinstance(value, str):
		if len(value) > MAX_BODY:
			frappe.throw(_("Request is too large."))
		try:
			return json.loads(value)
		except ValueError:
			frappe.throw(_("Malformed request."))
	frappe.throw(_("Malformed request."))
