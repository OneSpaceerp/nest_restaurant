"""Return allowances: cumulative over-return protection against the original rows."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import D, round_money


class ReturnError(ValueError):
	pass


@dataclass
class SoldRow:
	row_id: str  # original invoice item row name
	item_code: str
	qty: Decimal
	net_amount: Decimal  # after line and allocated invoice discounts
	returned_qty: Decimal = Decimal(0)  # sum over submitted returns (absolute)
	serial_nos: tuple[str, ...] = ()
	returned_serials: tuple[str, ...] = ()


def plan_return(rows: list[SoldRow], request: dict[str, dict], precision: int = 2) -> list[dict]:
	"""Validate `{row_id: {"qty": n, "serial_nos": [...]}}` and return refundable lines.

	Refund per unit is the original *net* unit price, so promotions are clawed back proportionally.
	"""
	by_id = {r.row_id: r for r in rows}
	plan = []
	for row_id, ask in request.items():
		row = by_id.get(row_id)
		if not row:
			raise ReturnError(f"Row {row_id} is not on the original sale")
		qty = D(ask.get("qty"))
		left = row.qty - row.returned_qty
		if qty <= 0:
			raise ReturnError("Return quantity must be more than zero")
		if qty > left:
			raise ReturnError(f"{row.item_code}: only {left} can still be returned")
		serials = tuple(ask.get("serial_nos") or ())
		if row.serial_nos:
			if len(serials) != qty:
				raise ReturnError(f"{row.item_code}: choose the serial numbers being returned")
			bad = [s for s in serials if s not in row.serial_nos or s in row.returned_serials]
			if bad:
				raise ReturnError(f"{row.item_code}: serial numbers not returnable: {', '.join(bad)}")
		unit = row.net_amount / row.qty
		plan.append(
			{
				"row_id": row_id,
				"item_code": row.item_code,
				"qty": qty,
				"refund": round_money(unit * qty, precision),
				"serial_nos": list(serials),
			}
		)
	if not plan:
		raise ReturnError("Choose at least one item to return")
	return plan
