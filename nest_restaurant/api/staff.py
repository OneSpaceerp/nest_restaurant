# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Nest Restaurant cashier endpoints shared with every Nest app (counter sales, register, returns)."""

from nest_restaurant.kit.staff_api import (  # noqa: F401  re-exported whitelisted endpoints
	bootstrap,
	cash_movement,
	catalog_page,
	close_register,
	create_return,
	held_carts,
	hold_cart,
	open_register,
	promotions,
	quote,
	recent_sales,
	request_approval,
	resolve_scan,
	resume_cart,
	retry_close,
	returnable,
	set_pin,
	shift_summary,
	submit_sale,
	switch_user_check,
)
