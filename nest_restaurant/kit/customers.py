"""Customer lookup for the till.

Who a register may sell to is the POS Profile's decision (its customer groups, as in ERPNext's own
POS), not the cashier's Desk permissions on Customer: a cashier role usually has none, which made a
client-side Customer list come back empty. A full phone number is matched on its last 9 digits so
local (01020212493) and international (+20 102 021 2493) forms find each other, including numbers
that live only on a linked Contact; 4–6 digits match as a fragment of the number.
"""

import re

import frappe
from frappe import _
from frappe.utils.nestedset import get_descendants_of

LIMIT = 15
FIELDS = ["name", "customer_name", "mobile_no", "email_id"]


def allowed_groups(profile) -> list[str] | None:
	"""Customer groups this profile sells to, with their sub-groups; None means any group."""
	roots = [r.customer_group for r in (profile.get("customer_groups") or []) if r.customer_group]
	if not roots:
		return None
	groups = set(roots)
	for g in roots:
		groups.update(get_descendants_of("Customer Group", g, ignore_permissions=True))
	return sorted(groups)


def can_sell_to(profile, customer: str) -> bool:
	row = frappe.db.get_value("Customer", customer, ["disabled", "customer_group"], as_dict=True)
	if not row or row.disabled:
		return False
	groups = allowed_groups(profile)
	return groups is None or row.customer_group in groups


def _phone_key(query: str) -> str | None:
	digits = re.sub(r"\D", "", query)
	return digits[-9:] if len(digits) >= 4 else None


def _spaced_like(digits: str) -> str:
	# "%1%0%2%…%" also finds numbers stored with spaces, dashes or brackets; it can over-match, so
	# every hit is confirmed with _same_phone / _phone_has
	return "%" + "%".join(digits) + "%"


def _digits(value) -> str:
	return re.sub(r"\D", "", value or "")


def _phone_has(stored, key: str) -> bool:
	"""Search: a full number (7+ digits) matches on its last 9 digits, a fragment anywhere."""
	d = _digits(stored)
	return d.endswith(key) if len(key) >= 7 else key in d


def _same_phone(stored, key: str) -> bool:
	d = _digits(stored)
	return len(d) >= 7 and (d.endswith(key) or key.endswith(d[-9:]))


def search(profile, query: str) -> list[dict]:
	q = (query or "").strip()
	if len(q) < 2:
		return []
	filters: dict = {"disabled": 0}
	groups = allowed_groups(profile)
	if groups is not None:
		filters["customer_group"] = ["in", groups]
	like = f"%{q}%"
	or_filters = [["customer_name", "like", like], ["name", "like", like], ["email_id", "like", like]]
	phone = _phone_key(q)
	if phone:
		or_filters.append(["mobile_no", "like", _spaced_like(phone) if len(phone) >= 7 else f"%{phone}%"])
	text = q.lower()
	found = [
		c
		for c in frappe.get_all(
			"Customer", filters=filters, or_filters=or_filters, fields=FIELDS, order_by="customer_name asc", limit=LIMIT * 2
		)
		if text in (c.customer_name or "").lower() or text in c.name.lower() or text in (c.email_id or "").lower()
		or (phone and _phone_has(c.mobile_no, phone))
	][:LIMIT]

	if phone and len(phone) >= 7 and len(found) < LIMIT:
		rows = frappe.get_all(
			"Contact Phone", filters={"parenttype": "Contact", "phone": ["like", _spaced_like(phone)]}, fields=["parent", "phone"], limit=50
		)
		contacts = list(dict.fromkeys(r.parent for r in rows if _phone_has(r.phone, phone)))
		if contacts:
			linked = frappe.get_all(
				"Dynamic Link",
				filters={"parenttype": "Contact", "parent": ["in", contacts], "link_doctype": "Customer"},
				pluck="link_name",
				limit=50,
			)
			have = {c.name for c in found}
			extra = [n for n in dict.fromkeys(linked) if n not in have]
			if extra:
				found += frappe.get_all(
					"Customer", filters={**filters, "name": ["in", extra]}, fields=FIELDS, limit=LIMIT - len(found)
				)

	return [{"name": c.name, "customer_name": c.customer_name, "phone": c.mobile_no, "email": c.email_id} for c in found]


def _default_group(profile) -> str:
	"""First non-group customer group the profile sells to, else Selling Settings' default."""
	for g in allowed_groups(profile) or []:
		if not frappe.db.get_value("Customer Group", g, "is_group"):
			return g
	g = frappe.db.get_single_value("Selling Settings", "customer_group")
	if g and not frappe.db.get_value("Customer Group", g, "is_group"):
		return g
	frappe.throw(_("Set a default Customer Group in Selling Settings (or on the POS Profile) to add customers at the till."))


def _existing_by_phone(phone_key: str) -> str | None:
	like = _spaced_like(phone_key)
	for c in frappe.get_all("Customer", filters={"disabled": 0, "mobile_no": ["like", like]}, fields=["name", "mobile_no"], limit=20):
		if _same_phone(c.mobile_no, phone_key):
			return c.name
	rows = frappe.get_all("Contact Phone", filters={"parenttype": "Contact", "phone": ["like", like]}, fields=["parent", "phone"], limit=20)
	contacts = [r.parent for r in rows if _same_phone(r.phone, phone_key)]
	if contacts:
		linked = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Contact", "parent": ["in", contacts], "link_doctype": "Customer"},
			pluck="link_name",
			limit=1,
		)
		if linked:
			return linked[0]
	return None


def create(profile, customer_name: str, mobile_no: str = "", email_id: str = "") -> dict:
	"""Add a customer from the till. A phone that already belongs to a customer returns that customer
	instead of a duplicate, so a double tap or a returning shopper never creates two records."""
	customer_name = " ".join((customer_name or "").split())[:140]
	mobile_no = (mobile_no or "").strip()[:20]
	email_id = (email_id or "").strip()[:140]
	if len(customer_name) < 2:
		frappe.throw(_("Enter the customer's name."))
	phone_key = _phone_key(mobile_no) if mobile_no else None
	if mobile_no and (not phone_key or len(_digits(mobile_no)) < 7 or not re.fullmatch(r"\+?[\d\s()-]{7,20}", mobile_no)):
		frappe.throw(_("Enter a valid mobile number."))
	if email_id and not frappe.utils.validate_email_address(email_id):
		frappe.throw(_("Enter a valid email address."))

	if phone_key and (found := _existing_by_phone(phone_key)):
		row = frappe.db.get_value("Customer", found, FIELDS, as_dict=True)
		return {"name": row.name, "customer_name": row.customer_name, "phone": row.mobile_no, "email": row.email_id, "existing": True}

	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": customer_name,
			"customer_type": "Individual",
			"customer_group": _default_group(profile),
			"territory": frappe.db.get_single_value("Selling Settings", "territory") or None,
			"mobile_no": mobile_no or None,
			"email_id": email_id or None,
		}
	)
	# the register's assignment authorises this (checked by the caller); cashiers rarely have Desk
	# create rights on Customer. ERPNext passes the flag on to the primary Contact it creates.
	doc.flags.ignore_permissions = True
	doc.insert()
	return {"name": doc.name, "customer_name": doc.customer_name, "phone": mobile_no or None, "email": email_id or None, "existing": False}
