# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Menu builder for managers: sections, dishes and option groups in one place.

A dish is three ERPNext/Nest records kept in step: the ERPNext Item (what is sold and invoiced), its
Item Price on the register's selling price list, and the Nest Restaurant Menu Item (how it shows on
the menu). A priced option ("+62 combo") is billed through its own non-stock Item, created here, so
ERPNext prices, taxes and reports cover add-ons too. Managers rarely have Desk rights on Item and
Item Price, so after the role and register checks those writes skip document permissions.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from nest_restaurant.kit import access, audit

MENU_ITEM = "Nest Restaurant Menu Item"
SECTION = "Nest Restaurant Menu Section"
GROUP = "Nest Restaurant Modifier Group"
REGISTER = "Nest Restaurant Register"
FLAGS = ("sold_out", "guest_visible")


def _guard(register: str):
	access.require("manager")
	access.require_register(register)
	return frappe.get_cached_doc(REGISTER, register)


def _price_list(reg) -> str:
	return frappe.get_cached_value("POS Profile", reg.pos_profile, "selling_price_list")


def _prices(price_list: str, codes: list[str]) -> dict[str, float]:
	rows = frappe.get_all(
		"Item Price",
		{"price_list": price_list, "item_code": ["in", codes or ["__none__"]], "customer": ["is", "not set"]},
		["item_code", "price_list_rate"],
		order_by="valid_from desc",
	)
	out: dict[str, float] = {}
	for r in rows:
		out.setdefault(r.item_code, flt(r.price_list_rate))
	return out


def _set_price(price_list: str, item_code: str, rate: float) -> None:
	name = frappe.db.get_value("Item Price", {"price_list": price_list, "item_code": item_code, "customer": ["is", "not set"]}, "name")
	if name:
		if flt(frappe.db.get_value("Item Price", name, "price_list_rate")) != flt(rate):
			doc = frappe.get_doc("Item Price", name)
			doc.price_list_rate = flt(rate)
			doc.flags.ignore_permissions = True
			doc.save()
		return
	doc = frappe.get_doc({"doctype": "Item Price", "price_list": price_list, "item_code": item_code, "price_list_rate": flt(rate)})
	doc.flags.ignore_permissions = True
	doc.insert()


def _item_groups() -> list[str]:
	return frappe.get_all("Item Group", {"is_group": 0}, pluck="name", order_by="name asc")


def _default_item_group(section: str | None, register: str) -> str:
	if section:
		code = frappe.db.get_value(MENU_ITEM, {"register": register, "section": section}, "item_code")
		if code and (g := frappe.db.get_value("Item", code, "item_group")):
			return g
	for g in (frappe.db.get_single_value("Stock Settings", "item_group"), _("Products"), "Products"):
		if g and frappe.db.exists("Item Group", g):
			return g
	groups = _item_groups()
	if not groups:
		frappe.throw(_("Create an Item Group in ERPNext first."))
	return groups[0]


def _uom() -> str:
	uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos"
	return uom if frappe.db.exists("UOM", uom) else (frappe.db.get_value("UOM", {}, "name") or "Nos")


def _new_item_code(base: str) -> str:
	base = " ".join(base.split())[:120] or "Dish"
	if not frappe.db.exists("Item", base):
		return base
	return f"{base}-{frappe.generate_hash(length=4).upper()}"


def _upsert_item(item_code: str | None, *, name: str, item_group: str, image: str | None, description: str | None) -> str:
	if item_code and frappe.db.exists("Item", item_code):
		item = frappe.get_doc("Item", item_code)
		item.item_name = name[:140]
		item.item_group = item_group or item.item_group
		if image:
			item.image = image
		if description is not None:
			item.description = description or item.item_name
		item.flags.ignore_permissions = True
		item.save()
		return item.name
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": _new_item_code(name),
			"item_name": name[:140],
			"item_group": item_group,
			"stock_uom": _uom(),
			"is_stock_item": 0,
			"is_sales_item": 1,
			"include_item_in_manufacturing": 0,
			"image": image or None,
			"description": description or name,
		}
	)
	item.flags.ignore_permissions = True
	item.insert()
	return item.name


# ------------------------------------------------------------------------------------------ read


def load(register: str) -> dict:
	reg = _guard(register)
	price_list = _price_list(reg)
	items = frappe.get_all(
		MENU_ITEM,
		{"register": register},
		["name", "item_code", "display_name", "display_name_ar", "section", "sequence", "sold_out", "guest_visible",
		 "default_course", "description", "allergens", "dietary", "image"],
		order_by="sequence asc, display_name asc",
	)
	codes = [i.item_code for i in items]
	prices = _prices(price_list, codes)
	meta = {r.name: r for r in frappe.get_all("Item", {"name": ["in", codes or ["__none__"]]}, ["name", "image", "item_group", "disabled"])}
	links: dict[str, list[str]] = {}
	for r in frappe.get_all("Nest Restaurant Menu Item Modifier", {"parenttype": MENU_ITEM, "parent": ["in", [i.name for i in items] or ["__none__"]]}, ["parent", "modifier_group", "idx"], order_by="idx asc"):
		links.setdefault(r.parent, []).append(r.modifier_group)

	sections = frappe.get_all(SECTION, {"register": register}, ["name", "section_name", "section_name_ar", "sequence"], order_by="sequence asc, section_name asc")
	known = {s.section_name for s in sections}
	for name in sorted({i.section for i in items if i.section and i.section not in known}):
		sections.append(frappe._dict(name=None, section_name=name, section_name_ar=None, sequence=len(sections)))

	groups = []
	for g in frappe.get_all(GROUP, pluck="name", order_by="group_name asc"):
		doc = frappe.get_cached_doc(GROUP, g)
		opt_prices = _prices(price_list, [o.price_item for o in doc.options if o.price_item])
		opt_images = dict(frappe.get_all("Item", {"name": ["in", [o.price_item for o in doc.options if o.price_item] or ["__none__"]]}, ["name", "image"], as_list=True))
		groups.append(
			{
				"name": doc.name,
				"group_name": doc.group_name,
				"min_select": cint(doc.min_select),
				"max_select": cint(doc.max_select),
				"options": [
					{
						"option_code": o.option_code,
						"option_name": o.option_name,
						"description": o.get("description") or "",
						"image": o.get("image") or opt_images.get(o.price_item) or "",
						"price": opt_prices.get(o.price_item, 0.0) if o.price_item else 0.0,
						"sold_out": cint(o.sold_out),
					}
					for o in doc.options
				],
			}
		)

	return {
		"register": register,
		"currency": frappe.get_cached_value("POS Profile", reg.pos_profile, "currency"),
		"price_list": price_list,
		"item_groups": _item_groups(),
		"sections": [{"name": s.name, "section_name": s.section_name, "section_name_ar": s.section_name_ar or ""} for s in sections],
		"items": [
			{
				"name": i.name,
				"item_code": i.item_code,
				"display_name": i.display_name or i.item_code,
				"display_name_ar": i.display_name_ar or "",
				"section": i.section or "",
				"price": prices.get(i.item_code),
				"image": i.image or (meta.get(i.item_code) or {}).get("image") or "",
				"item_group": (meta.get(i.item_code) or {}).get("item_group") or "",
				"description": i.description or "",
				"allergens": i.allergens or "",
				"dietary": i.dietary or "",
				"sold_out": cint(i.sold_out),
				"guest_visible": cint(i.guest_visible),
				"default_course": cint(i.default_course) or 1,
				"groups": links.get(i.name, []),
			}
			for i in items
		],
		"groups": groups,
	}


# ------------------------------------------------------------------------------------------ write


def save_item(register: str, data: dict) -> dict:
	"""Create or update one dish: ERPNext Item, its price on the register's price list, and the menu entry."""
	reg = _guard(register)
	name = " ".join((data.get("display_name") or "").split())
	name_ar = " ".join((data.get("display_name_ar") or "").split())
	if not (name or name_ar):
		frappe.throw(_("Give the dish a name."))
	section = " ".join((data.get("section") or "").split())[:140]
	if not section:
		frappe.throw(_("Choose a menu section."))
	price = flt(data.get("price"))
	if price <= 0:
		frappe.throw(_("Enter a price above zero."))
	groups = [g for g in (data.get("groups") or []) if frappe.db.exists(GROUP, g)]

	existing = frappe.get_doc(MENU_ITEM, data["name"]) if data.get("name") else None
	if existing and existing.register != register:
		frappe.throw(_("This dish belongs to another register."), frappe.PermissionError)
	item_group = data.get("item_group") if frappe.db.exists("Item Group", data.get("item_group") or "") else _default_item_group(section, register)
	item_code = _upsert_item(
		existing.item_code if existing else None,
		name=name or name_ar,
		item_group=item_group,
		image=data.get("image") or None,
		description=data.get("description"),
	)
	_set_price(_price_list(reg), item_code, price)

	doc = existing or frappe.get_doc({"doctype": MENU_ITEM, "register": register, "item_code": item_code})
	if not existing:
		doc.sequence = 10 * (frappe.db.count(MENU_ITEM, {"register": register, "section": section}) + 1)  # new dishes go last
	doc.update(
		{
			"display_name": name or name_ar,
			"display_name_ar": name_ar,
			"section": section,
			"description": (data.get("description") or "")[:1000],
			"allergens": (data.get("allergens") or "")[:140],
			"dietary": (data.get("dietary") or "")[:140],
			"image": data.get("image") or None,
			"sold_out": cint(data.get("sold_out")),
			"guest_visible": cint(data.get("guest_visible", 1)),
			"default_course": min(max(cint(data.get("default_course")) or 1, 1), 9),
		}
	)
	doc.set("modifier_groups", [{"modifier_group": g} for g in groups])
	doc.flags.ignore_permissions = True
	doc.save() if existing else doc.insert()
	_ensure_section(register, section)
	audit.log("menu.item_saved", MENU_ITEM, doc.name, register=register, item=item_code, price=price)
	return load(register)


def _ensure_section(register: str, section: str) -> None:
	if frappe.db.exists(SECTION, {"register": register, "section_name": section}):
		return
	seq = frappe.db.count(SECTION, {"register": register})
	doc = frappe.get_doc({"doctype": SECTION, "register": register, "section_name": section, "sequence": seq})
	doc.flags.ignore_permissions = True
	doc.insert()


def set_flag(register: str, name: str, field: str, value) -> dict:
	_guard(register)
	if field not in FLAGS:
		frappe.throw(_("This cannot be changed here."))
	if frappe.db.get_value(MENU_ITEM, name, "register") != register:
		frappe.throw(_("This dish belongs to another register."), frappe.PermissionError)
	frappe.db.set_value(MENU_ITEM, name, field, cint(value))
	audit.log("menu.flag", MENU_ITEM, name, register=register, field=field, value=cint(value))
	return {"name": name, field: cint(value)}


def remove_item(register: str, name: str) -> dict:
	"""Take a dish off this register's menu. The ERPNext Item and its sales history stay."""
	_guard(register)
	if frappe.db.get_value(MENU_ITEM, name, "register") != register:
		frappe.throw(_("This dish belongs to another register."), frappe.PermissionError)
	frappe.delete_doc(MENU_ITEM, name, ignore_permissions=True)
	audit.log("menu.item_removed", MENU_ITEM, name, register=register)
	return load(register)


def save_sections(register: str, sections: list[dict]) -> dict:
	"""Sections in their new order; renamed ones carry their dishes along. A section can only be
	dropped once it has no dishes."""
	_guard(register)
	seen: set[str] = set()
	for i, s in enumerate(sections or []):
		new = " ".join((s.get("section_name") or "").split())[:140]
		if not new or new in seen:
			frappe.throw(_("Every section needs its own name."))
		seen.add(new)
		old = (s.get("old_name") or "").strip()
		if old and old != new:
			if frappe.db.exists(SECTION, {"register": register, "section_name": new}):
				frappe.throw(_("There is already a section called {0}.").format(new))
			frappe.db.set_value(MENU_ITEM, {"register": register, "section": old}, "section", new)
			for n in frappe.get_all(SECTION, {"register": register, "section_name": old}, pluck="name"):
				frappe.delete_doc(SECTION, n, ignore_permissions=True)
		name = frappe.db.get_value(SECTION, {"register": register, "section_name": new}, "name")
		doc = frappe.get_doc(SECTION, name) if name else frappe.get_doc({"doctype": SECTION, "register": register, "section_name": new})
		doc.section_name_ar = (s.get("section_name_ar") or "")[:140]
		doc.sequence = i
		doc.flags.ignore_permissions = True
		doc.save() if name else doc.insert()
	for d in frappe.get_all(SECTION, {"register": register}, ["name", "section_name"]):
		if d.section_name not in seen:
			if frappe.db.exists(MENU_ITEM, {"register": register, "section": d.section_name}):
				frappe.throw(_("Move or remove the dishes in {0} before removing the section.").format(d.section_name))
			frappe.delete_doc(SECTION, d.name, ignore_permissions=True)
	audit.log("menu.sections_saved", register=register, sections=len(seen))
	return load(register)


def reorder_items(register: str, section: str, names: list[str]) -> dict:
	_guard(register)
	for i, n in enumerate(names or []):
		if frappe.db.get_value(MENU_ITEM, n, ["register", "section"]) != (register, section):
			frappe.throw(_("A dish in this list belongs elsewhere."))
		frappe.db.set_value(MENU_ITEM, n, "sequence", (i + 1) * 10, update_modified=False)
	return {"ok": True}


def save_group(register: str, data: dict) -> dict:
	"""Create or update an option group (e.g. Size: required, choose 1; Combo: optional, choose 1).
	Options with a price bill through their own non-stock Item on the register's price list."""
	reg = _guard(register)
	price_list = _price_list(reg)
	group_name = " ".join((data.get("group_name") or "").split())[:140]
	if not group_name:
		frappe.throw(_("Give the option group a name."))
	min_s, max_s = cint(data.get("min_select")), cint(data.get("max_select")) or 1
	if min_s < 0 or max_s < 1 or min_s > max_s:
		frappe.throw(_("Choices must be between the minimum and the maximum, with at least one allowed."))
	opts_in = data.get("options") or []
	if not opts_in:
		frappe.throw(_("Add at least one option."))
	if min_s > len(opts_in):
		frappe.throw(_("The group requires more choices than it has options."))

	doc = frappe.get_doc(GROUP, data["name"]) if data.get("name") else None
	if not doc and frappe.db.exists(GROUP, group_name):
		frappe.throw(_("There is already an option group called {0}. Pick it from the list instead.").format(group_name))
	doc = doc or frappe.get_doc({"doctype": GROUP, "group_name": group_name})
	old = {o.option_code: o for o in (doc.options or [])}
	item_group = _default_item_group(None, register)
	rows = []
	for o in opts_in:
		oname = " ".join((o.get("option_name") or "").split())[:140]
		if not oname:
			frappe.throw(_("Every option needs a name."))
		code = o.get("option_code") if o.get("option_code") in old else frappe.generate_hash(length=8)
		price = flt(o.get("price"))
		if price < 0:
			frappe.throw(_("Option prices cannot be negative."))
		price_item = old[code].price_item if code in old else None
		if price > 0:
			price_item = _upsert_item(price_item, name=f"{group_name} – {oname}", item_group=item_group, image=o.get("image") or None, description=o.get("description") or oname)
			_set_price(price_list, price_item, price)
		else:
			price_item = None
		rows.append(
			{
				"option_name": oname,
				"option_code": code,
				"description": (o.get("description") or "")[:140],
				"image": o.get("image") or None,
				"price_item": price_item,
				"sold_out": cint(o.get("sold_out")),
			}
		)
	doc.min_select, doc.max_select = min_s, max_s
	doc.set("options", rows)
	doc.flags.ignore_permissions = True
	doc.save() if doc.get("name") and not doc.is_new() else doc.insert()
	audit.log("menu.group_saved", GROUP, doc.name, register=register, options=len(rows))
	return load(register)
