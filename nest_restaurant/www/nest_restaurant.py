# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
# Serves www/nest-restaurant.html (the built staff PWA shell) at /nest-restaurant and /nest-restaurant/<path>.

from nest_restaurant.kit.boot import staff_context

no_cache = 1


def get_context(context):
	return staff_context(context, "/nest-restaurant")
