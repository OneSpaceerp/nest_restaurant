"""Scanner input: normalisation, GTIN check digits, variable-measure barcodes and GS1 element strings.

The server resolves the final item (barcode table, serial/batch numbers, item codes); this module
only turns a raw scan into a structured candidate so the same rules apply to keyboard-wedge scanners,
phone cameras and paired scanners.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

# AIM symbology identifiers some scanners prepend (]C1 = GS1-128, ]E0 = EAN-13, ]d2 = GS1 DataMatrix…)
_AIM_PREFIX = re.compile(r"^\][A-Za-z][0-9A-Za-z]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1c\x1e\x1f\x7f]")  # keep \x1d (GS / FNC1)
GS = "\x1d"
MAX_SCAN_LENGTH = 128


class ScanError(ValueError):
	pass


@dataclass
class VariableMeasureRule:
	"""In-store barcode carrying a weight or price, e.g. prefix "20", 5-digit item, 5-digit value."""

	prefix: str
	item_length: int
	value_length: int
	kind: str  # "weight" | "price"
	decimals: int
	verify_check_digit: bool = True

	@property
	def total_length(self) -> int:
		return len(self.prefix) + self.item_length + self.value_length + 1


@dataclass
class ScanCandidate:
	raw: str
	code: str
	symbology: str  # gtin | variable | gs1 | text
	gtin: str | None = None
	item_ref: str | None = None
	weight: Decimal | None = None
	price: Decimal | None = None
	batch_no: str | None = None
	serial_no: str | None = None
	expiry: str | None = None
	notes: list[str] = field(default_factory=list)


def normalise(raw: str) -> str:
	if raw is None:
		raise ScanError("Empty scan")
	value = str(raw)
	if len(value) > MAX_SCAN_LENGTH:
		raise ScanError("Scan is too long")
	value = _AIM_PREFIX.sub("", value.strip())
	value = _CONTROL.sub("", value).strip()
	if not value:
		raise ScanError("Empty scan")
	return value


def gtin_check_digit(body: str) -> int:
	"""Check digit for a GTIN body (all digits except the check digit), any length 7-17."""
	if not body.isdigit():
		raise ScanError("GTIN body must be digits")
	total = 0
	for i, ch in enumerate(reversed(body)):
		total += int(ch) * (3 if i % 2 == 0 else 1)
	return (10 - total % 10) % 10


def is_valid_gtin(code: str) -> bool:
	return code.isdigit() and len(code) in (8, 12, 13, 14) and gtin_check_digit(code[:-1]) == int(code[-1])


def to_gtin14(code: str) -> str:
	return code.zfill(14)


def parse_variable(code: str, rules: list[VariableMeasureRule]) -> ScanCandidate | None:
	for rule in rules:
		if not (code.isdigit() and len(code) == rule.total_length and code.startswith(rule.prefix)):
			continue
		if rule.verify_check_digit and gtin_check_digit(code[:-1]) != int(code[-1]):
			continue
		start = len(rule.prefix)
		item_ref = code[start : start + rule.item_length]
		raw_value = code[start + rule.item_length : start + rule.item_length + rule.value_length]
		value = Decimal(int(raw_value)).scaleb(-rule.decimals)
		cand = ScanCandidate(raw=code, code=code, symbology="variable", item_ref=item_ref)
		if rule.kind == "weight":
			cand.weight = value
		elif rule.kind == "price":
			cand.price = value
		else:
			raise ScanError(f"Unknown variable-measure kind {rule.kind!r}")
		return cand
	return None


# Fixed-length GS1 application identifiers we act on; everything else variable up to GS.
_FIXED_AI = {"01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "17": 6}
_VAR_AI = {"10", "21", "22", "240", "241"}


def parse_gs1(code: str) -> ScanCandidate | None:
	"""Parse a GS1 element string such as `0109501101530003` + `17260131` + `10ABC` + GS + `21XYZ`.

	Returns None when the text does not start with a known AI, so plain codes fall through.
	"""
	if code.startswith(GS):
		text = code[1:]
	elif code[:2] in ("01", "02") and len(code) >= 16 and is_valid_gtin(code[2:16]):
		text = code
	else:
		return None
	cand = ScanCandidate(raw=code, code=code, symbology="gs1")
	i = 0
	while i < len(text):
		if text[i] == GS:
			i += 1
			continue
		ai2, ai3, ai4 = text[i : i + 2], text[i : i + 3], text[i : i + 4]
		if ai2 in _FIXED_AI:
			n = _FIXED_AI[ai2]
			value = text[i + 2 : i + 2 + n]
			if len(value) != n:
				raise ScanError(f"Truncated GS1 field ({ai2})")
			if ai2 in ("01", "02"):
				if not is_valid_gtin(value):
					raise ScanError("GS1 GTIN has a bad check digit")
				cand.gtin = value
			elif ai2 == "17":
				cand.expiry = f"20{value[0:2]}-{value[2:4]}-{value[4:6]}"
			i += 2 + n
		elif ai4[:3] == "310" and ai4[3:].isdigit():
			value = text[i + 4 : i + 10]
			cand.weight = Decimal(int(value)).scaleb(-int(ai4[3]))
			i += 10
		elif ai3 in _VAR_AI or ai2 in _VAR_AI:
			ai = ai3 if ai3 in _VAR_AI else ai2
			end = text.find(GS, i + len(ai))
			end = len(text) if end == -1 else end
			value = text[i + len(ai) : end][:20]
			if ai == "10":
				cand.batch_no = value
			elif ai == "21":
				cand.serial_no = value
			i = end
		else:
			cand.notes.append(f"Ignored unknown GS1 data at position {i}")
			break
	return cand


def parse_scan(raw: str, rules: list[VariableMeasureRule] | None = None) -> ScanCandidate:
	code = normalise(raw)
	cand = parse_gs1(code)
	if cand:
		return cand
	cand = parse_variable(code, rules or [])
	if cand:
		return cand
	if is_valid_gtin(code):
		return ScanCandidate(raw=raw, code=code, symbology="gtin", gtin=code)
	return ScanCandidate(raw=raw, code=code, symbology="text")


def lookup_keys(cand: ScanCandidate) -> list[str]:
	"""Ordered barcode strings to try against `Item Barcode` (as stored, then normalised GTIN forms)."""
	keys: list[str] = []
	for value in (cand.code, cand.gtin):
		if not value:
			continue
		keys.append(value)
		if value.isdigit() and len(value) in (8, 12, 13, 14):
			keys.append(to_gtin14(value))
			stripped = value.lstrip("0")
			for length in (13, 12, 8):
				if len(stripped) <= length:
					keys.append(stripped.zfill(length))
	seen: set[str] = set()
	return [k for k in keys if not (k in seen or seen.add(k))]
