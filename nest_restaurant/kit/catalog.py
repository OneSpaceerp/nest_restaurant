"""Catalog snapshot, search and scan resolution for staff; a public price-check subset for clients.

Staff snapshots feed the offline catalog. Public views never include cost, valuation, supplier data,
exact stock levels or customer-specific prices.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from ..core.scan import ScanError, VariableMeasureRule, lookup_keys, parse_scan

MAX_PAGE = 500


def _price_map(price_list: str, item_codes: list[str] | None = None) -> dict:
	filters = {"price_list": price_list, "selling": 1}
	if item_codes is not None:
		filters["item_code"] = ["in", item_codes or ["__none__"]]
	rows = frappe.get_all(
		"Item Price",
		filters=filters,
		fields=["item_code", "price_list_rate", "uom", "valid_from", "valid_upto", "customer"],
		order_by="valid_from desc",
	)
	today = frappe.utils.getdate()
	prices: dict[str, dict] = {}
	for r in rows:
		if r.customer:  # customer-specific prices are resolved by ERPNext at checkout, never published
			continue
		if (r.valid_from and r.valid_from > today) or (r.valid_upto and r.valid_upto < today):
			continue
		prices.setdefault(r.item_code, {"rate": flt(r.price_list_rate), "uom": r.uom})
	return prices


def snapshot(profile_name: str, start: int = 0, page_length: int = MAX_PAGE, since: str | None = None) -> dict:
	"""One page of the staff catalog. Uses get_list so Item permissions still apply."""
	profile = frappe.get_cached_doc("POS Profile", profile_name)
	groups = [g.item_group for g in profile.get("item_groups") or []]
	filters = {"disabled": 0, "is_sales_item": 1, "has_variants": 0}
	if groups:
		filters["item_group"] = ["in", _descendants(groups)]
	if since:
		filters["modified"] = [">", since]
	items = frappe.get_list(
		"Item",
		filters=filters,
		fields=["name as item_code", "item_name", "item_group", "brand", "stock_uom", "image", "has_serial_no",
			"has_batch_no", "is_stock_item", "variant_of", "modified"],
		limit_start=cint(start),
		limit_page_length=min(cint(page_length) or MAX_PAGE, MAX_PAGE),
		order_by="item_name asc",
	)
	codes = [i.item_code for i in items]
	prices = _price_map(profile.selling_price_list, codes)
	barcodes = frappe.get_all("Item Barcode", filters={"parent": ["in", codes or ["__none__"]]}, fields=["parent", "barcode", "uom"])
	by_item: dict[str, list] = {}
	for b in barcodes:
		by_item.setdefault(b.parent, []).append({"barcode": b.barcode, "uom": b.uom})
	stock = _stock(profile.warehouse, codes)
	for i in items:
		price = prices.get(i.item_code)
		i["rate"] = price["rate"] if price else None
		i["price_uom"] = price["uom"] if price else None
		i["barcodes"] = by_item.get(i.item_code, [])
		i["available"] = stock.get(i.item_code) if i.is_stock_item else None
	return {"items": items, "next_start": cint(start) + len(items) if len(items) == min(cint(page_length) or MAX_PAGE, MAX_PAGE) else None,
		"price_list": profile.selling_price_list, "currency": profile.currency}


def _descendants(groups: list[str]) -> list[str]:
	out = set(groups)
	for g in groups:
		lft, rgt = frappe.get_cached_value("Item Group", g, ["lft", "rgt"]) or (None, None)
		if lft is not None:
			out.update(frappe.get_all("Item Group", {"lft": [">=", lft], "rgt": ["<=", rgt]}, pluck="name"))
	return sorted(out)


def _stock(warehouse: str | None, codes: list[str]) -> dict:
	if not warehouse or not codes:
		return {}
	rows = frappe.get_all("Bin", filters={"warehouse": warehouse, "item_code": ["in", codes]}, fields=["item_code", "actual_qty", "reserved_qty"])
	return {r.item_code: flt(r.actual_qty) - flt(r.reserved_qty) for r in rows}


def variable_rules() -> list[VariableMeasureRule]:
	raw = frappe.conf.get("nest_variable_barcodes") or "[]"
	try:
		return [VariableMeasureRule(**r) for r in (json.loads(raw) if isinstance(raw, str) else raw)]
	except Exception:
		return []


def resolve_scan(profile_name: str, raw: str) -> dict:
	"""Resolve a scan to exactly one sellable item, or explain why not (unknown / ambiguous / template)."""
	try:
		cand = parse_scan(raw, variable_rules())
	except ScanError as e:
		return {"status": "invalid", "message": str(e)}
	profile = frappe.get_cached_doc("POS Profile", profile_name)
	matches: list[dict] = []
	for key in lookup_keys(cand):
		for row in frappe.get_all("Item Barcode", filters={"barcode": key}, fields=["parent", "uom"]):
			matches.append({"item_code": row.parent, "uom": row.uom, "via": "barcode"})
		if matches:
			break
	if not matches and cand.item_ref:
		# Weighed/priced labels carry a PLU; it must be registered exactly as an Item Barcode.
		for row in frappe.get_all("Item Barcode", filters={"barcode": cand.item_ref}, fields=["parent", "uom"]):
			matches.append({"item_code": row.parent, "uom": row.uom, "via": "variable"})
	if not matches and cand.serial_no is None and frappe.db.exists("Serial No", cand.code):
		sn = frappe.db.get_value("Serial No", cand.code, ["item_code", "status", "warehouse"], as_dict=True)
		if sn.status != "Active" or sn.warehouse != profile.warehouse:
			return {"status": "unavailable", "message": _("Serial number {0} is not in stock here.").format(cand.code)}
		cand.serial_no = cand.code
		matches.append({"item_code": sn.item_code, "uom": None, "via": "serial"})
	if not matches and frappe.db.exists("Batch", cand.code):
		cand.batch_no = cand.code
		matches.append({"item_code": frappe.db.get_value("Batch", cand.code, "item"), "uom": None, "via": "batch"})
	if not matches and frappe.db.exists("Item", {"name": cand.code, "disabled": 0}):
		matches.append({"item_code": cand.code, "uom": None, "via": "item_code"})
	unique = {m["item_code"]: m for m in matches}
	if not unique:
		return {"status": "unknown", "code": cand.code}
	if len(unique) > 1:
		return {"status": "ambiguous", "code": cand.code, "candidates": list(unique)}
	match = next(iter(unique.values()))
	item = frappe.get_cached_value("Item", match["item_code"], ["item_name", "has_variants", "disabled", "is_sales_item"], as_dict=True)
	if item.has_variants:
		variants = frappe.get_all("Item", {"variant_of": match["item_code"], "disabled": 0}, pluck="name", limit=50)
		return {"status": "variant_required", "item_code": match["item_code"], "variants": variants}
	if item.disabled or not item.is_sales_item:
		return {"status": "unavailable", "message": _("{0} is not for sale.").format(item.item_name)}
	price = _price_map(profile.selling_price_list, [match["item_code"]]).get(match["item_code"])
	return {
		"status": "ok",
		"item_code": match["item_code"],
		"item_name": item.item_name,
		"uom": match["uom"],
		"via": match["via"],
		"qty": str(cand.weight) if cand.weight is not None else "1",
		"price_override": str(cand.price) if cand.price is not None else None,
		"serial_no": cand.serial_no,
		"batch_no": cand.batch_no,
		"rate": price["rate"] if price else None,
	}


def public_view(profile_name: str, item_code: str) -> dict:
	"""What a client may see: name, image, description, list price, tax note, promotion titles,
	and coarse availability. No cost, supplier, valuation, warehouse or exact quantities."""
	profile = frappe.get_cached_doc("POS Profile", profile_name)
	item = frappe.db.get_value(
		"Item", item_code, ["item_name", "image", "description", "stock_uom", "disabled", "is_sales_item", "has_variants", "is_stock_item"], as_dict=True
	)
	if not item or item.disabled or not item.is_sales_item or item.has_variants:
		return {"status": "unavailable"}
	price = _price_map(profile.selling_price_list, [item_code]).get(item_code)
	if not price:
		return {"status": "unavailable"}
	qty = _stock(profile.warehouse, [item_code]).get(item_code) if item.is_stock_item else None
	availability = None if qty is None else ("in_stock" if qty > 5 else "low" if qty > 0 else "out")
	return {
		"status": "ok",
		"item_code": item_code,
		"item_name": item.item_name,
		"image": item.image,
		"description": frappe.utils.strip_html(item.description or "")[:300],
		"uom": price["uom"] or item.stock_uom,
		"rate": price["rate"],
		"currency": profile.currency,
		"price_includes_tax": _profile_tax_inclusive(profile),
		"availability": availability,
	}


def _profile_tax_inclusive(profile) -> bool | None:
	template = profile.taxes_and_charges
	if not template:
		return None
	return bool(frappe.get_all("Sales Taxes and Charges", {"parent": template, "included_in_print_rate": 1}, limit=1))
