"""Customer lookup for the till.

Who a register may sell to is the POS Profile's decision (its customer groups, as in ERPNext's own
POS), not the cashier's Desk permissions on Customer: a cashier role usually has none, which made a
client-side Customer list come back empty. Phones are matched on their last 9 digits so local
(01020212493) and international (+20 102 021 2493) forms find each other, including numbers that
live only on a linked Contact.
"""

import re

import frappe
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
	return digits[-9:] if len(digits) >= 6 else None


def _spaced_like(digits: str) -> str:
	# "%1%0%2%…%" also matches numbers stored with spaces, dashes or brackets
	return "%" + "%".join(digits) + "%"


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
		or_filters.append(["mobile_no", "like", _spaced_like(phone)])
	found = frappe.get_all(
		"Customer", filters=filters, or_filters=or_filters, fields=FIELDS, order_by="customer_name asc", limit=LIMIT
	)

	if phone and len(found) < LIMIT:
		contacts = frappe.get_all(
			"Contact Phone", filters={"parenttype": "Contact", "phone": ["like", _spaced_like(phone)]}, pluck="parent", limit=50
		)
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
