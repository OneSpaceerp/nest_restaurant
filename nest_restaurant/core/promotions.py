"""Nest promotion engine (authoritative). Used only when a register's pricing authority is `nest`.

Modes: percent, amount (per unit), fixed_price (per unit), bxgy (buy X get Y at a discount),
spend_save (bill threshold → amount off, allocated over eligible lines) and bundle (a set of items
for a fixed price). Every result is expressed as per-line discount amounts with attribution, so the
invoice carries ordinary `discount_amount` values and returns can refund the true net unit price.

Rules of combination, applied in this order:
1. Promotions are evaluated by (priority, name).
2. An `exclusive` promotion that applies claims its lines; nothing else may touch them.
3. A line receives at most one non-`stackable` promotion. `stackable` ones add on top.
4. A line's total discount never exceeds its gross value.

The TypeScript preview (`shared/pricing/promotions.ts`) implements the same rules and is checked
against the same fixtures (`fixtures/promotions.json`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal

from .money import D, allocate, round_money

KINDS = {"percent", "amount", "fixed_price", "bxgy", "spend_save", "bundle"}


class PromotionError(ValueError):
	pass


@dataclass
class Line:
	line_id: str
	item_code: str
	qty: Decimal
	rate: Decimal
	item_group: str = ""
	brand: str = ""

	@property
	def gross(self) -> Decimal:
		return self.qty * self.rate


@dataclass
class Context:
	at: datetime
	customer_group: str = ""
	profile: str = ""
	coupons: frozenset[str] = frozenset()


@dataclass
class Applied:
	promotion: str
	line_id: str
	amount: Decimal


@dataclass
class Result:
	applied: list[Applied] = field(default_factory=list)
	line_discounts: dict[str, Decimal] = field(default_factory=dict)
	total_discount: Decimal = Decimal(0)
	rejected_coupons: list[str] = field(default_factory=list)

	def as_dict(self) -> dict:
		return {
			"applied": [
				{"promotion": a.promotion, "line_id": a.line_id, "amount": str(a.amount)} for a in self.applied
			],
			"line_discounts": {k: str(v) for k, v in self.line_discounts.items()},
			"total_discount": str(self.total_discount),
			"rejected_coupons": self.rejected_coupons,
		}


def _parse_time(value) -> time | None:
	if not value:
		return None
	if isinstance(value, time):
		return value
	hh, mm, *_ = str(value).split(":")
	return time(int(hh), int(mm))


def is_active(promo: dict, ctx: Context) -> bool:
	if promo.get("disabled"):
		return False
	day = ctx.at.date().isoformat()
	if promo.get("valid_from") and day < str(promo["valid_from"]):
		return False
	if promo.get("valid_to") and day > str(promo["valid_to"]):
		return False
	days = promo.get("days_of_week")
	if days and ctx.at.weekday() not in days:
		return False
	start, end = _parse_time(promo.get("time_from")), _parse_time(promo.get("time_to"))
	now = ctx.at.time()
	if start and end:
		within = start <= now < end if start <= end else (now >= start or now < end)  # overnight window
		if not within:
			return False
	if promo.get("customer_groups") and ctx.customer_group not in promo["customer_groups"]:
		return False
	if promo.get("profiles") and ctx.profile not in promo["profiles"]:
		return False
	code = promo.get("coupon_code")
	if code and code.upper() not in {c.upper() for c in ctx.coupons}:
		return False
	return True


def _eligible(promo: dict, line: Line) -> bool:
	scope = promo.get("applies_to") or {}
	items, groups, brands = scope.get("items"), scope.get("item_groups"), scope.get("brands")
	if not (items or groups or brands):
		return True
	return (
		(bool(items) and line.item_code in items)
		or (bool(groups) and line.item_group in groups)
		or (bool(brands) and line.brand in brands)
	)


def _per_line(promo: dict, lines: list[Line], precision: int) -> dict[str, Decimal]:
	kind = promo["kind"]
	value = D(promo.get("value"))
	out: dict[str, Decimal] = {}
	min_qty = D(promo.get("min_qty") or 0)
	if min_qty and sum((l.qty for l in lines), Decimal(0)) < min_qty:
		return out
	min_amount = D(promo.get("min_amount") or 0)
	if min_amount and sum((l.gross for l in lines), Decimal(0)) < min_amount:
		return out

	if kind == "percent":
		for l in lines:
			out[l.line_id] = round_money(l.gross * value / 100, precision)
	elif kind == "amount":
		for l in lines:
			out[l.line_id] = round_money(min(value, l.rate) * l.qty, precision)
	elif kind == "fixed_price":
		for l in lines:
			if l.rate > value:
				out[l.line_id] = round_money((l.rate - value) * l.qty, precision)
	elif kind == "bxgy":
		buy, get = int(promo.get("buy_qty") or 0), int(promo.get("get_qty") or 0)
		pct = D(promo.get("get_discount_percent") if promo.get("get_discount_percent") is not None else 100)
		if buy <= 0 or get <= 0:
			raise PromotionError(f"{promo['name']}: buy and get quantities must be positive")
		# Unit-level: the cheapest eligible units are the "get" units.
		units: list[tuple[Decimal, str]] = []
		for l in lines:
			whole = int(l.qty)
			units.extend((l.rate, l.line_id) for _ in range(whole))
		groups = len(units) // (buy + get)
		max_apps = promo.get("max_applications")
		if max_apps:
			groups = min(groups, int(max_apps))
		free_units = sorted(units, key=lambda u: (u[0], u[1]))[: groups * get]
		for rate, line_id in free_units:
			out[line_id] = out.get(line_id, Decimal(0)) + rate * pct / 100
		out = {k: round_money(v, precision) for k, v in out.items()}
	elif kind == "spend_save":
		threshold = D(promo.get("threshold"))
		eligible_total = sum((l.gross for l in lines), Decimal(0))
		if eligible_total >= threshold > 0:
			times = 1 if not promo.get("repeat") else int(eligible_total // threshold)
			amount = min(D(promo.get("discount_amount")) * times, eligible_total)
			parts = allocate(amount, [l.gross for l in lines], precision)
			out = {l.line_id: p for l, p in zip(lines, parts, strict=True) if p}
	elif kind == "bundle":
		need = {b["item_code"]: D(b["qty"]) for b in promo.get("bundle_items") or []}
		if not need:
			raise PromotionError(f"{promo['name']}: a bundle needs items")
		have: dict[str, Decimal] = {}
		for l in lines:
			have[l.item_code] = have.get(l.item_code, Decimal(0)) + l.qty
		sets = min(int(have.get(code, 0) // q) for code, q in need.items())
		if sets <= 0:
			return out
		bundle_lines = [l for l in lines if l.item_code in need]
		# Value of exactly `sets` bundles, consumed from lines in order.
		consumed: list[tuple[Line, Decimal]] = []
		remaining = {code: q * sets for code, q in need.items()}
		for l in bundle_lines:
			take = min(l.qty, remaining[l.item_code])
			if take > 0:
				consumed.append((l, take))
				remaining[l.item_code] -= take
		value_at_price = sum((l.rate * q for l, q in consumed), Decimal(0))
		discount = max(value_at_price - D(promo.get("bundle_price")) * sets, Decimal(0))
		parts = allocate(discount, [l.rate * q for l, q in consumed], precision)
		for (l, _q), p in zip(consumed, parts, strict=True):
			if p:
				out[l.line_id] = out.get(l.line_id, Decimal(0)) + p
	else:
		raise PromotionError(f"Unknown promotion kind {kind!r}")
	return {k: v for k, v in out.items() if v > 0}


def evaluate(lines: list[Line], promotions: list[dict], ctx: Context, precision: int = 2) -> Result:
	result = Result()
	by_id = {l.line_id: l for l in lines}
	discount = {l.line_id: Decimal(0) for l in lines}
	exclusive_lock: set[str] = set()
	non_stackable_taken: set[str] = set()

	coupon_promos = {p["coupon_code"].upper() for p in promotions if p.get("coupon_code")}
	result.rejected_coupons = sorted(c for c in ctx.coupons if c.upper() not in coupon_promos)

	ordered = sorted(
		(p for p in promotions if p.get("kind") in KINDS and is_active(p, ctx)),
		key=lambda p: (0 if p.get("exclusive") else 1, int(p.get("priority") or 100), p["name"]),
	)
	for promo in ordered:
		stackable = bool(promo.get("stackable")) and not promo.get("exclusive")
		candidates = [
			l
			for l in lines
			if _eligible(promo, l)
			and l.line_id not in exclusive_lock
			and (stackable or l.line_id not in non_stackable_taken)
			and l.qty > 0
		]
		if not candidates:
			continue
		amounts = _per_line(promo, candidates, precision)
		for line_id, amt in amounts.items():
			room = by_id[line_id].gross - discount[line_id]
			amt = min(amt, max(room, Decimal(0)))
			if amt <= 0:
				continue
			discount[line_id] += amt
			result.applied.append(Applied(promo["name"], line_id, amt))
			if promo.get("exclusive"):
				exclusive_lock.add(line_id)
			if not stackable:
				non_stackable_taken.add(line_id)

	result.line_discounts = {k: round_money(v, precision) for k, v in discount.items() if v > 0}
	result.total_discount = round_money(sum(result.line_discounts.values(), Decimal(0)), precision)
	return result
