"""Production routing: which station cooks which line, and what a "send" actually adds.

Two defects in the reference apps shape this module:
- URY/Mosaic KOT recovery initialised one item list *outside* the per-unit loop, so a second
  station's recovered ticket also carried the first station's items. Here every grouping builds a
  fresh list per station inside the comprehension; `route_lines` cannot leak by construction.
- Re-sending a whole order duplicated food. Here a send only routes the *delta* between ordered
  and already-sent quantity per line, and cancellations route as negative deltas (void tickets).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .money import D


@dataclass(frozen=True)
class Station:
	name: str
	item_groups: frozenset[str] = frozenset()
	items: frozenset[str] = frozenset()
	is_default: bool = False


@dataclass
class OrderLine:
	line_id: str
	item_code: str
	item_group: str
	qty: Decimal
	sent_qty: Decimal = Decimal(0)
	course: int = 1
	seat: int | None = None
	note: str = ""
	modifiers: tuple[str, ...] = ()
	held: bool = False  # course not fired yet


@dataclass
class TicketLine:
	line_id: str
	item_code: str
	qty: Decimal  # negative = cancel
	course: int
	seat: int | None
	note: str
	modifiers: tuple[str, ...]


@dataclass
class Ticket:
	station: str
	lines: list[TicketLine] = field(default_factory=list)

	@property
	def is_void(self) -> bool:
		return all(l.qty < 0 for l in self.lines)


class RoutingError(ValueError):
	pass


def station_for(line: OrderLine, stations: list[Station]) -> str | None:
	"""Item-specific routing wins over group routing; the default station catches the rest."""
	for s in stations:
		if line.item_code in s.items:
			return s.name
	for s in stations:
		if line.item_group in s.item_groups:
			return s.name
	for s in stations:
		if s.is_default:
			return s.name
	return None


def pending_delta(line: OrderLine) -> Decimal:
	return D(line.qty) - D(line.sent_qty)


def route_lines(
	lines: list[OrderLine], stations: list[Station], fire_courses: set[int] | None = None
) -> tuple[list[Ticket], list[str]]:
	"""Group the unsent deltas into one ticket per station.

	`fire_courses` limits a send to the given courses (course firing); held lines are skipped.
	Returns (tickets, unrouted line ids). Lines with no station are reported, never dropped silently.
	"""
	by_station: dict[str, list[TicketLine]] = {}
	unrouted: list[str] = []
	for line in lines:
		delta = pending_delta(line)
		if delta == 0 or line.held:
			continue
		if fire_courses is not None and line.course not in fire_courses and delta > 0:
			continue
		station = station_for(line, stations)
		if station is None:
			unrouted.append(line.line_id)
			continue
		by_station.setdefault(station, []).append(
			TicketLine(line.line_id, line.item_code, delta, line.course, line.seat, line.note, line.modifiers)
		)
	tickets = [Ticket(station=name, lines=list(rows)) for name, rows in sorted(by_station.items())]
	return tickets, unrouted


def mark_sent(lines: list[OrderLine], tickets: list[Ticket]) -> None:
	"""Advance `sent_qty` exactly by what the tickets carried (called in the same transaction)."""
	sent: dict[str, Decimal] = {}
	for t in tickets:
		for tl in t.lines:
			sent[tl.line_id] = sent.get(tl.line_id, Decimal(0)) + tl.qty
	for line in lines:
		if line.line_id in sent:
			line.sent_qty = D(line.sent_qty) + sent[line.line_id]


def recover_missing(
	lines: list[OrderLine], stations: list[Station], ticketed_qty: dict[tuple[str, str], Decimal]
) -> list[Ticket]:
	"""Rebuild only what is genuinely missing per (station, line) after a failed send.

	`ticketed_qty` maps (station, line_id) → quantity already present on tickets. Each station's
	list is created fresh, so recovered tickets never contain another station's items.
	"""
	missing: dict[str, list[TicketLine]] = {}
	for line in lines:
		station = station_for(line, stations)
		if station is None:
			continue
		have = ticketed_qty.get((station, line.line_id), Decimal(0))
		gap = D(line.sent_qty) - have
		if gap > 0:
			missing.setdefault(station, []).append(
				TicketLine(line.line_id, line.item_code, gap, line.course, line.seat, line.note, line.modifiers)
			)
	return [Ticket(station=s, lines=rows) for s, rows in sorted(missing.items())]


def minutes_late(age_minutes: float, warn_after: float, late_after: float) -> str:
	if age_minutes >= late_after:
		return "late"
	if age_minutes >= warn_after:
		return "warning"
	return "on_time"
