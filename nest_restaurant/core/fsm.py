"""Explicit state machines for every long-lived Nest record.

Each machine lists its states and the only transitions allowed between them. Controllers call
`assert_transition` in `validate`, so an impossible status can never be saved, whether it comes from
the API, Desk or a data import. The same tables are documented in docs/state-machines.md and exported
to the frontend for UI affordances.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class TransitionError(ValueError):
	pass


@dataclass(frozen=True)
class Machine:
	name: str
	initial: str
	transitions: dict[str, frozenset[str]]
	terminal: frozenset[str] = field(default_factory=frozenset)

	@property
	def states(self) -> frozenset[str]:
		found = set(self.transitions)
		for targets in self.transitions.values():
			found |= targets
		return frozenset(found)

	def can(self, current: str | None, target: str) -> bool:
		if current is None or current == "":
			return target == self.initial
		if current == target:
			return True
		return target in self.transitions.get(current, frozenset())

	def assert_transition(self, current: str | None, target: str) -> None:
		if target not in self.states:
			raise TransitionError(f"{self.name}: unknown status {target!r}")
		if not self.can(current, target):
			raise TransitionError(f"{self.name}: cannot move from {current!r} to {target!r}")

	def as_dict(self) -> dict:
		return {
			"name": self.name,
			"initial": self.initial,
			"terminal": sorted(self.terminal),
			"transitions": {k: sorted(v) for k, v in self.transitions.items()},
		}


def _m(name, initial, transitions, terminal=()):
	return Machine(
		name=name,
		initial=initial,
		transitions={k: frozenset(v) for k, v in transitions.items()},
		terminal=frozenset(terminal),
	)


REGISTER_SESSION = _m(
	"Register Session",
	"Open",
	{
		"Open": {"Closing"},
		# Closing: counts recorded, invoices frozen; waiting for consolidation or a retry.
		"Closing": {"Closed", "Close Failed", "Open"},
		"Close Failed": {"Closing"},
	},
	terminal={"Closed"},
)

SALE_REQUEST = _m(
	"Sale Request",
	"Received",
	{
		"Received": {"Posted", "Rejected", "Needs Review"},
		"Needs Review": {"Posted", "Rejected"},
	},
	terminal={"Posted", "Rejected"},
)

CLIENT_BASKET = _m(
	"Client Basket",
	"Submitted",
	{
		"Submitted": {"Claimed", "Cancelled", "Expired"},
		"Claimed": {"Imported", "Submitted", "Cancelled"},  # back to Submitted = released/reassigned
		"Imported": {"Completed", "Cancelled"},
	},
	terminal={"Completed", "Cancelled", "Expired"},
)

SCANNER_PAIRING = _m(
	"Scanner Pairing",
	"Pending",
	{"Pending": {"Active", "Expired", "Revoked"}, "Active": {"Revoked", "Expired"}},
	terminal={"Expired", "Revoked"},
)

RESTAURANT_ORDER = _m(
	"Restaurant Order",
	"Open",
	{
		"Open": {"Bill Requested", "Billed", "Cancelled", "Merged"},
		"Bill Requested": {"Open", "Billed", "Cancelled"},
		# Billed: bill printed/locked for payment; reopening needs authority (checked by the service).
		"Billed": {"Open", "Partly Paid", "Paid"},
		"Partly Paid": {"Paid"},
	},
	terminal={"Paid", "Cancelled", "Merged"},
)

KITCHEN_TICKET = _m(
	"Kitchen Ticket",
	"New",
	{
		"New": {"Preparing", "Ready", "Cancelled"},
		"Preparing": {"Ready", "New", "Cancelled"},  # back to New = recall
		"Ready": {"Served", "Preparing"},
		"Served": {"Ready"},  # recall a mistaken "served"
	},
	terminal={"Cancelled"},
)

TABLE = _m(
	"Table",
	"Free",
	{
		"Free": {"Occupied", "Reserved", "Out of Service"},
		"Reserved": {"Occupied", "Free"},
		"Occupied": {"Free", "Needs Cleaning"},
		"Needs Cleaning": {"Free"},
		"Out of Service": {"Free"},
	},
)

RESERVATION = _m(
	"Reservation",
	"Requested",
	{
		"Requested": {"Confirmed", "Cancelled"},
		"Confirmed": {"Seated", "Cancelled", "No Show"},
		"Seated": {"Completed"},
	},
	terminal={"Completed", "Cancelled", "No Show"},
)

GUEST_SUBMISSION = _m(
	"Guest Submission",
	"Received",
	{
		"Received": {"Accepted", "Awaiting Approval", "Rejected"},
		"Awaiting Approval": {"Accepted", "Rejected"},
	},
	terminal={"Accepted", "Rejected"},
)

SYNC_ENTRY = _m(
	"Sync Entry",
	"Queued",
	{
		"Queued": {"Sending"},
		"Sending": {"Acknowledged", "Queued", "Rejected", "Ambiguous"},
		"Ambiguous": {"Sending", "Acknowledged", "Rejected"},
		"Rejected": {"Needs Review"},
		"Needs Review": {"Acknowledged", "Discarded"},
	},
	terminal={"Acknowledged", "Discarded"},
)

PAYMENT_INTENT = _m(
	"Payment Intent",
	"Created",
	{
		"Created": {"Pending", "Failed", "Cancelled"},
		"Pending": {"Captured", "Failed", "Cancelled"},
		"Captured": {"Consumed", "Refunded"},
		"Consumed": {"Refunded"},
	},
	terminal={"Failed", "Cancelled", "Refunded"},
)

MACHINES = {
	m.name: m
	for m in (
		REGISTER_SESSION,
		SALE_REQUEST,
		CLIENT_BASKET,
		SCANNER_PAIRING,
		RESTAURANT_ORDER,
		KITCHEN_TICKET,
		TABLE,
		RESERVATION,
		GUEST_SUBMISSION,
		SYNC_ENTRY,
		PAYMENT_INTENT,
	)
}
