"""Decimal money helpers: rounding, tender allocation, change and proportional splits.

All amounts are `Decimal`. Callers pass the currency precision (number of decimals) from
ERPNext rather than assuming two, so currencies such as KWD (3) and JPY (0) behave.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable


class MoneyError(ValueError):
	pass


def D(value) -> Decimal:
	"""Coerce to Decimal without float artefacts; reject NaN/inf."""
	if isinstance(value, Decimal):
		result = value
	elif value is None or value == "":
		result = Decimal(0)
	else:
		try:
			result = Decimal(str(value))
		except InvalidOperation as e:
			raise MoneyError(f"Not a number: {value!r}") from e
	if not result.is_finite():
		raise MoneyError(f"Not a finite number: {value!r}")
	return result


def quantum(precision: int) -> Decimal:
	if precision < 0 or precision > 9:
		raise MoneyError("precision must be between 0 and 9")
	return Decimal(1).scaleb(-precision)


def round_money(value, precision: int = 2) -> Decimal:
	return D(value).quantize(quantum(precision), rounding=ROUND_HALF_UP)


def round_to_increment(value, increment) -> Decimal:
	"""Cash rounding, e.g. to 0.05 or 0.25. An increment of 0 returns the value unchanged."""
	inc = D(increment)
	if inc <= 0:
		return D(value)
	return ((D(value) / inc).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * inc


def allocate(total, weights: Iterable, precision: int = 2) -> list[Decimal]:
	"""Split `total` across `weights` proportionally, so that the parts sum exactly to `total`.

	Largest-remainder method: every part is rounded down to the quantum, then the leftover quanta go
	to the parts with the largest remainders (ties to the earliest). Used for bill-level discounts,
	split-by-amount and allocating a payment over lines.
	"""
	total = round_money(total, precision)
	weights = [D(w) for w in weights]
	if not weights:
		return []
	if any(w < 0 for w in weights):
		raise MoneyError("weights cannot be negative")
	weight_sum = sum(weights)
	q = quantum(precision)
	if weight_sum == 0:
		weights = [Decimal(1)] * len(weights)
		weight_sum = Decimal(len(weights))
	raw = [total * w / weight_sum for w in weights]
	sign = 1 if total >= 0 else -1
	floored = [(abs(r) // q) * q * sign for r in raw]
	remainders = [abs(r) - abs(f) for r, f in zip(raw, floored, strict=True)]
	leftover = int((abs(total) - sum(abs(f) for f in floored)) / q)
	order = sorted(range(len(raw)), key=lambda i: (-remainders[i], i))
	for i in order[:leftover]:
		floored[i] += q * sign
	return floored


def settle_tenders(amount_due, tenders: list[dict], precision: int = 2) -> dict:
	"""Validate a split tender and compute change.

	`tenders` is a list of `{"mode": str, "amount": number, "allows_change": bool}`. Only tenders that
	allow change (cash) may overpay; change comes out of them. Returns paid, change and the amount
	each tender actually settles (what is posted to the invoice's payment rows).
	"""
	due = round_money(amount_due, precision)
	if due < 0:
		raise MoneyError("amount due cannot be negative; use a return")
	rows = []
	for t in tenders:
		amt = round_money(t.get("amount"), precision)
		if amt < 0:
			raise MoneyError("A payment cannot be negative.")
		if amt == 0:
			continue
		rows.append({"mode": t["mode"], "amount": amt, "allows_change": bool(t.get("allows_change"))})
	paid = sum((r["amount"] for r in rows), Decimal(0))
	non_change = sum((r["amount"] for r in rows if not r["allows_change"]), Decimal(0))
	if non_change > due:
		raise MoneyError("Card or account payments cannot exceed the amount due.")
	change = paid - due if paid > due else Decimal(0)
	remaining_change = change
	for r in reversed(rows):
		r["settled"] = r["amount"]
		if remaining_change and r["allows_change"]:
			take = min(remaining_change, r["amount"])
			r["settled"] = r["amount"] - take
			remaining_change -= take
	return {
		"due": due,
		"paid": paid,
		"change": round_money(change, precision),
		"outstanding": round_money(max(due - paid, Decimal(0)), precision),
		"rows": rows,
	}
