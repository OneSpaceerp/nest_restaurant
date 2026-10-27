# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
# Serves www/nest-restaurant-customer.html (the built guest PWA shell) at /nest-restaurant/customer/<path>.

from nest_restaurant.kit.boot import customer_context

no_cache = 1


def get_context(context):
	return customer_context(context, "/nest-restaurant/customer")
