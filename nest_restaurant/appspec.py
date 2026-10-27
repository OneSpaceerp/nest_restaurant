# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Identity of this app for the vendored kit (see nest_restaurant/kit/VENDORED.md)."""

from nest_restaurant.kit.spec import AppSpec

SPEC = AppSpec(
	app="nest_restaurant",
	prefix="Nest Restaurant",
	field_prefix="nest_rest",
	route="/nest-restaurant",
	desk_page="nest-restaurant",
	roles={
		"cashier": "Nest Restaurant Cashier",
		"waiter": "Nest Restaurant Waiter",
		"kitchen": "Nest Restaurant Kitchen",
		"supervisor": "Nest Restaurant Supervisor",
		"manager": "Nest Restaurant Manager",
	},
	modules=(
		"Nest Restaurant Setup",
		"Nest Restaurant Registers",
		"Nest Restaurant Service",
		"Nest Restaurant Menu",
		"Nest Restaurant Floor",
	),
	extra_invoice_fields=(
		{
			"fieldname": "nest_rest_order",
			"fieldtype": "Link",
			"label": "Nest Restaurant order",
			"options": "Nest Restaurant Order",
			"insert_after": "nest_rest_request",
			"read_only": 1,
			"no_copy": 1,
			"search_index": 1,
		},
	),
)
