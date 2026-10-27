"""Bill splitting: by item quantities, by seat, into equal parts, or by explicit amounts.

Every split returns *line portions* (line id, qty, amount) per part, so each part becomes an
ordinary invoice with ordinary lines, and parts always add back up to the original check.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import D, allocate, round_money


class SplitError(ValueError):
	pass


@dataclass
class CheckLine:
	line_id: str
	qty: Decimal
	amount: Decimal  # net line amount after discounts, before invoice-level taxes
	seat: int | None = None
	paid_qty: Decimal = Decimal(0)


def by_items(lines: list[CheckLine], selection: dict[str, Decimal], precision: int = 2) -> list[dict]:
	"""One part made of chosen quantities. Amounts are pro rata on the line's net amount."""
	part = []
	by_id = {l.line_id: l for l in lines}
	for line_id, qty in selection.items():
		qty = D(qty)
		line = by_id.get(line_id)
		if not line:
			raise SplitError(f"Unknown line {line_id}")
		available = line.qty - line.paid_qty
		if qty <= 0 or qty > available:
			raise SplitError(f"Line {line_id}: only {available} left to pay")
		part.append({"line_id": line_id, "qty": qty, "amount": round_money(line.amount * qty / line.qty, precision)})
	if not part:
		raise SplitError("Choose at least one item")
	return part


def by_seat(lines: list[CheckLine], precision: int = 2) -> dict[str, list[dict]]:
	"""Seat-assigned lines go to their seat; shared (unseated) lines are divided across seats."""
	seats = sorted({l.seat for l in lines if l.seat is not None})
	if not seats:
		raise SplitError("No seats are assigned on this check")
	parts: dict[str, list[dict]] = {str(s): [] for s in seats}
	for l in lines:
		remaining_qty = l.qty - l.paid_qty
		if remaining_qty <= 0:
			continue
		remaining_amount = round_money(l.amount * remaining_qty / l.qty, precision)
		if l.seat is not None:
			parts[str(l.seat)].append({"line_id": l.line_id, "qty": remaining_qty, "amount": remaining_amount})
		else:
			shares = allocate(remaining_amount, [1] * len(seats), precision)
			qty_shares = [remaining_qty / len(seats)] * len(seats)
			for s, amt, q in zip(seats, shares, qty_shares, strict=True):
				parts[str(s)].append({"line_id": l.line_id, "qty": q, "amount": amt, "shared": True})
	return parts


def equal_parts(total, count: int, precision: int = 2) -> list[Decimal]:
	if count < 2 or count > 50:
		raise SplitError("Split into 2 to 50 parts")
	return allocate(total, [1] * count, precision)


def by_amounts(total, amounts: list, precision: int = 2) -> list[Decimal]:
	values = [round_money(a, precision) for a in amounts]
	if any(v <= 0 for v in values):
		raise SplitError("Each part must be more than zero")
	if sum(values) != round_money(total, precision):
		raise SplitError("Parts must add up to the bill total")
	return values


def service_charge(base, percent, precision: int = 2) -> Decimal:
	if D(percent) < 0 or D(percent) > 100:
		raise SplitError("Service charge must be between 0 and 100 percent")
	return round_money(D(base) * D(percent) / 100, precision)
