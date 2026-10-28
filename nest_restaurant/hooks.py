app_name = "nest_restaurant"
app_title = "Nest Restaurant"
app_publisher = "Nest Software Development (nsdLabs)"
app_description = "Restaurant and cafe point of sale for ERPNext: floor, waiters, kitchen display, guest ordering"
app_email = "info@nsd-eg.com"
app_license = "UNLICENSED"  # pending a publisher licensing decision; see docs/provenance.md
app_logo_url = "/assets/nest_restaurant/images/nest-restaurant-logo.png?v=08c9951e"
app_home = "/desk/nest-restaurant"

required_apps = ["erpnext"]

app_include_icons = ["/assets/nest_restaurant/icons/nest_restaurant-icons.svg"]

add_to_apps_screen = [
	{
		"name": app_name,
		"logo": app_logo_url,
		"title": app_title,
		"route": app_home,
		"has_permission": "nest_restaurant.kit.access.check_app_permission",
		"sequence_id": 51,
	}
]

website_route_rules = [
	{"from_route": "/nest-restaurant/customer", "to_route": "nest-restaurant-customer"},
	{"from_route": "/nest-restaurant/customer/<path:app_path>", "to_route": "nest-restaurant-customer"},
	{"from_route": "/nest-restaurant/<path:app_path>", "to_route": "nest-restaurant"},
]

# Serves <route>/sw.js and <route>/customer/sw.js with the right scope (see kit/sw.py)
page_renderer = ["nest_restaurant.kit.sw.ServiceWorkerRenderer"]

after_install = "nest_restaurant.kit.install.after_install"
after_migrate = "nest_restaurant.kit.install.after_migrate"

doc_events = {
	"Sales Invoice": {
		"validate": "nest_restaurant.kit.install.guard_invoice",
		"before_cancel": "nest_restaurant.kit.install.guard_invoice",
	},
	"POS Invoice": {
		"validate": "nest_restaurant.kit.install.guard_invoice",
		"before_cancel": "nest_restaurant.kit.install.guard_invoice",
	},
}

permission_query_conditions = {
	"Nest Restaurant Register": "nest_restaurant.kit.access.register_query",
	"Nest Restaurant Register Session": "nest_restaurant.kit.access.session_query",
	"Nest Restaurant Sale Request": "nest_restaurant.kit.access.sale_request_query",
}

has_permission = {
	"Nest Restaurant Register": "nest_restaurant.kit.access.register_has_permission",
}

scheduler_events = {
	"cron": {
		"*/5 * * * *": ["nest_restaurant.kit.register.follow_up_consolidations"],
		"*/10 * * * *": ["nest_restaurant.services.kitchen.recovery_sweep"],
	},
}

export_python_type_annotations = True
