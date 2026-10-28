# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Menu builder endpoints (managers). See services/menu_builder.py."""

import frappe

from nest_restaurant.kit.util import obj
from nest_restaurant.services import menu_builder


@frappe.whitelist()
def load(register_name: str) -> dict:
	return menu_builder.load(register_name)


@frappe.whitelist(methods=["POST"])
def save_item(register_name: str, item) -> dict:
	return menu_builder.save_item(register_name, obj(item, {}))


@frappe.whitelist(methods=["POST"])
def set_flag(register_name: str, name: str, field: str, value: int) -> dict:
	return menu_builder.set_flag(register_name, name, field, value)


@frappe.whitelist(methods=["POST"])
def remove_item(register_name: str, name: str) -> dict:
	return menu_builder.remove_item(register_name, name)


@frappe.whitelist(methods=["POST"])
def save_sections(register_name: str, sections) -> dict:
	return menu_builder.save_sections(register_name, obj(sections, []))


@frappe.whitelist(methods=["POST"])
def reorder_items(register_name: str, section: str, names) -> dict:
	return menu_builder.reorder_items(register_name, section, obj(names, []))


@frappe.whitelist(methods=["POST"])
def save_group(register_name: str, group) -> dict:
	return menu_builder.save_group(register_name, obj(group, {}))
