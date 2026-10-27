# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Integration tests. Run on a disposable test site:

    bench --site test_site set-config allow_tests true
    bench --site test_site run-tests --app nest_restaurant
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from nest_restaurant.core.tokens import sign_context
from nest_restaurant.kit.shared_flows import CASHIER_A, SharedFlows, SharedSetup
from nest_restaurant.kit.testing import key, make_stock_item
from nest_restaurant.services import guests, kitchen, orders


class TestNestRestaurantSharedFlows(SharedFlows, IntegrationTestCase):
	"""Register, sale, return and security invariants (shared kit) on Nest Restaurant documents."""


class TestNestRestaurantService(SharedSetup, IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.drink = make_stock_item("NREST-COLA", 20)
		frappe.db.set_value("Item", cls.drink, "item_group", "Products")
		frappe.db.set_value("Item", cls.item, "item_group", "_Test Item Group")
		floor = frappe.get_doc({"doctype": "Nest Restaurant Floor", "floor_name": "Main", "register": cls.register}).insert(ignore_if_duplicate=True)
		cls.tables = []
		for label in ("12", "13"):
			name = f"{floor.name}-{label}"
			if not frappe.db.exists("Nest Restaurant Table", name):
				frappe.get_doc({"doctype": "Nest Restaurant Table", "table_label": label, "floor": floor.name, "seats": 4}).insert()
			cls.tables.append(name)
		for st, group, default in (("Test Kitchen", "_Test Item Group", 1), ("Test Bar", "Products", 0)):
			if not frappe.db.exists("Nest Restaurant Station", st):
				frappe.get_doc({"doctype": "Nest Restaurant Station", "station_name": st, "register": cls.register, "is_default": default,
					"routes": [{"route_type": "Item Group", "value": group}]}).insert()
		for code in (cls.item, cls.drink):
			if not frappe.db.exists("Nest Restaurant Menu Item", f"{cls.register}-{code}"):
				frappe.get_doc({"doctype": "Nest Restaurant Menu Item", "item_code": code, "register": cls.register, "display_name": code}).insert()
		frappe.db.commit()

	def _open(self, table):
		frappe.set_user(CASHIER_A)
		frappe.get_doc("User", CASHIER_A).add_roles("Nest Restaurant Waiter")
		return orders.open_order(self.register, table, 2, "Dine-in", key("open-"))["order"]

	def test_send_routes_each_station_only_its_lines_and_is_idempotent(self):
		order = self._open(self.tables[0])
		orders.add_lines(order, [{"item_code": self.item, "qty": 2}, {"item_code": self.drink, "qty": 1}], key("add-"))
		k = key("send-")
		first = orders.send(order, k)
		again = orders.send(order, k)
		self.assertEqual(first["tickets"], again["tickets"])
		self.assertEqual(frappe.db.count("Nest Restaurant Kitchen Ticket", {"order": order}), 2)
		bar = frappe.get_all("Nest Restaurant Kitchen Ticket", {"order": order, "station": "Test Bar"}, pluck="name")[0]
		self.assertEqual(frappe.get_all("Nest Restaurant Kitchen Ticket Line", {"parent": bar}, pluck="item_code"), [self.drink])

	def test_second_round_sends_only_the_delta(self):
		order = self._open(self.tables[0])
		added = orders.add_lines(order, [{"item_code": self.item, "qty": 1}], key("add-"))
		orders.send(order, key("send-"))
		orders.add_lines(order, [{"item_code": self.item, "qty": 1}], key("add-"))
		res = orders.send(order, key("send-"))
		self.assertEqual(len(res["tickets"]), 1)
		self.assertEqual(res["tickets"][0]["kind"], "Addition")
		self.assertTrue(added["added"])

	def test_recovery_with_two_stations_never_mixes_items(self):
		order = self._open(self.tables[0])
		orders.add_lines(order, [{"item_code": self.item, "qty": 1}, {"item_code": self.drink, "qty": 1}], key("add-"))
		orders.send(order, key("send-"))
		kitchen_ticket = frappe.get_all("Nest Restaurant Kitchen Ticket", {"order": order, "station": "Test Kitchen"}, pluck="name")[0]
		frappe.delete_doc("Nest Restaurant Kitchen Ticket", kitchen_ticket, force=True, ignore_permissions=True)  # simulate a lost ticket
		frappe.set_user("Administrator")
		recovered = kitchen.verify_and_recover(order)
		self.assertEqual(len(recovered), 1)
		lines = frappe.get_all("Nest Restaurant Kitchen Ticket Line", {"parent": recovered[0]}, pluck="item_code")
		self.assertEqual(lines, [self.item])
		self.assertEqual(kitchen.verify_and_recover(order), [], "nothing missing → nothing re-cooked")

	def test_forged_or_foreign_table_codes_are_rejected(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			guests.start_visit(sign_context("x" * 48, "table", {"register": self.register, "table": self.tables[0]}, 3600))

	def test_guest_joining_an_occupied_table_needs_the_visit_code(self):
		order = self._open(self.tables[1])
		secret = frappe.get_single("Nest Restaurant Settings").get_password("signing_secret")
		frappe.set_user("Guest")
		visit = guests.start_visit(sign_context(secret, "table", {"register": self.register, "table": self.tables[1]}, 3600))
		self.assertTrue(visit["needs_visit_code"])
		with self.assertRaises(frappe.PermissionError):
			guests.submit(visit["token"], [{"item_code": self.item, "qty": 1}], key("g-"))
		code = frappe.db.get_value("Nest Restaurant Order", order, "visit_code")
		self.assertTrue(guests.confirm(visit["token"], code)["confirmed"])

	def test_direct_guest_order_reaches_kitchen_without_reentry(self):
		frappe.db.set_single_value("Nest Restaurant Settings", "guest_ordering_mode", "Direct to kitchen")
		secret = frappe.get_single("Nest Restaurant Settings").get_password("signing_secret")
		table = self.tables[0]
		frappe.db.set_value("Nest Restaurant Table", table, {"status": "Free", "current_order": None})
		frappe.set_user("Guest")
		visit = guests.start_visit(sign_context(secret, "table", {"register": self.register, "table": table}, 3600))
		res = guests.submit(visit["token"], [{"item_code": self.drink, "qty": 2}], key("g-"))
		self.assertEqual(res["status"], "Accepted")
		self.assertTrue(frappe.db.exists("Nest Restaurant Kitchen Ticket", {"order": res["order"], "station": "Test Bar"}))

	def test_booking_capacity_is_enforced(self):
		from nest_restaurant.services import bookings

		frappe.db.set_single_value("Nest Restaurant Settings", {"booking_enabled": 1, "booking_online_seats": 6, "booking_max_party": 6, "booking_lead_minutes": 0,
			"booking_opens": "00:00:00", "booking_closes": "23:59:00", "booking_slot_minutes": 30})
		start = add_to_date(now_datetime(), days=1).replace(hour=19, minute=0, second=0, microsecond=0)
		frappe.set_user("Guest")
		bookings.book_online(self.register, "A", "0100000001", 4, str(start), key("bk-"))
		with self.assertRaises(Exception):
			bookings.book_online(self.register, "B", "0100000002", 4, str(start), key("bk-"))
