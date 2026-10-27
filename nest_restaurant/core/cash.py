"""Register cash: denomination counts, expected drawer and variance."""

from __future__ import annotations

from decimal import Decimal

from .money import D, round_money


class CashError(ValueError):
	pass


def count_denominations(counts: list[dict], precision: int = 2) -> Decimal:
	total = Decimal(0)
	for row in counts:
		value, n = D(row.get("value")), D(row.get("count"))
		if value <= 0 or n < 0 or n != n.to_integral_value():
			raise CashError("Denominations need a positive value and a whole, non-negative count")
		total += value * n
	return round_money(total, precision)


def expected_by_mode(opening: dict, sales: dict, refunds: dict, movements: dict, precision: int = 2) -> dict:
	"""Expected amount per mode of payment: opening float + sales − refunds + cash in − cash out."""
	modes = set(opening) | set(sales) | set(refunds) | set(movements)
	return {
		m: round_money(D(opening.get(m)) + D(sales.get(m)) - D(refunds.get(m)) + D(movements.get(m)), precision)
		for m in sorted(modes)
	}


def variance(expected: dict, counted: dict, precision: int = 2) -> dict:
	modes = set(expected) | set(counted)
	return {m: round_money(D(counted.get(m)) - D(expected.get(m)), precision) for m in sorted(modes)}


def needs_reason(variances: dict, tolerance) -> bool:
	tol = D(tolerance)
	return any(abs(D(v)) > tol for v in variances.values())
