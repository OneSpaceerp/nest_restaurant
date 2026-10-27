"""Bounded validation for untrusted cart payloads (client baskets, guest orders, offline replays).

The server never accepts prices, discounts, owners or statuses from these payloads: only catalog
identifiers it has published, quantities within bounds and short notes. Everything else is dropped.
"""

from __future__ import annotations

from decimal import Decimal

from .money import D, MoneyError

MAX_LINES = 100
MAX_QTY = Decimal(999)
MAX_NOTE = 140
MAX_MODIFIERS = 20


class PayloadError(ValueError):
	pass


def clean_note(value) -> str:
	text = " ".join(str(value or "").split())
	return text[:MAX_NOTE]


def clean_lines(
	raw_lines, allowed_items: set[str], allow_fractional: set[str] | None = None, allowed_modifiers: set[str] | None = None
) -> list[dict]:
	if not isinstance(raw_lines, list) or not raw_lines:
		raise PayloadError("Add at least one item")
	if len(raw_lines) > MAX_LINES:
		raise PayloadError(f"A basket can hold up to {MAX_LINES} lines")
	allow_fractional = allow_fractional or set()
	cleaned = []
	for raw in raw_lines:
		if not isinstance(raw, dict):
			raise PayloadError("Malformed line")
		item = str(raw.get("item_code") or "")
		if item not in allowed_items:
			raise PayloadError("One of the items is not available here")
		try:
			qty = D(raw.get("qty"))
		except MoneyError as e:
			raise PayloadError("Quantity must be a number") from e
		if qty <= 0 or qty > MAX_QTY:
			raise PayloadError("Quantity is out of range")
		if qty != qty.to_integral_value() and item not in allow_fractional:
			raise PayloadError("This item is sold in whole units")
		mods = [str(m) for m in (raw.get("modifiers") or [])][:MAX_MODIFIERS]
		if allowed_modifiers is not None and any(m not in allowed_modifiers for m in mods):
			raise PayloadError("One of the options is not available")
		cleaned.append(
			{
				"item_code": item,
				"qty": qty,
				"note": clean_note(raw.get("note")),
				"modifiers": mods,
				"course": max(1, min(int(raw.get("course") or 1), 9)),
				"seat": int(raw["seat"]) if str(raw.get("seat") or "").isdigit() else None,
			}
		)
	return cleaned
