# Nest Restaurant

Restaurant and café point of sale for ERPNext v16 by **nsdLabs** (Nest Software Development · info@nsd-eg.com).
A complete POS on its own — it does not need Nest POS.

- Floor with live table states, covers, age, bill and food-ready flags; takeaway/delivery orders.
- Waiter/cashier order screen: menu sections, option groups with limits, allergens, seats and courses; rounds
  kept on the device until accepted; send only new lines, one ticket per station; hold/fire courses; voids with
  approval; transfer and merge; bill lock; split by items or seat; service charge and tips.
- Kitchen display per station with timers, late alerts, recall, void tickets, audible alert with mute, and
  recovery that never mixes stations.
- Guest ordering from a signed table QR: visit code to join an occupied table, direct-to-kitchen or
  approval mode, live status, bill and waiter requests.
- Reservations with a public booking page (capacity checked under a lock).
- Counter till, shifts, returns and offline cash sales shared with Nest POS through the same kit.
- English and Arabic (RTL), installable staff and guest PWAs, Desk page inside Frappe's Dock and Sidebar.

Recipes: model a dish as a non-stock ERPNext **Product Bundle** of its ingredients; the invoice consumes the
ingredients and never the dish itself.

Docs (in the Nest source tree): `docs/installation.md`, `docs/feature-parity-matrix.md`, `docs/verification.md`.

Requires Frappe and ERPNext v16.52+ (v16 only). **Status:** bench verification pending.

Licence: not yet decided by the publisher; see `license.txt`.
