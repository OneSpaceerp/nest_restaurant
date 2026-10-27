"""Canonical request fingerprints for idempotent commands.

A command is stored under its client key with the SHA-256 of its canonical JSON. A retry with the
same key and fingerprint returns the stored result; the same key with a different fingerprint is a
conflict that must be rejected, never silently resolved.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from decimal import Decimal

KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{15,79}$")

# Fields that legitimately differ between a first attempt and its retry.
VOLATILE_FIELDS = frozenset({"attempt", "client_sent_at", "retry_count", "network"})


class IdempotencyError(ValueError):
	pass


def validate_key(key: str | None) -> str:
	key = (key or "").strip()
	if not KEY_PATTERN.match(key):
		raise IdempotencyError("A request key of 16-80 safe characters is required.")
	return key


def new_key(prefix: str = "") -> str:
	return f"{prefix}{uuid.uuid4().hex}"


def _normalise(value):
	if isinstance(value, dict):
		return {k: _normalise(v) for k, v in sorted(value.items()) if k not in VOLATILE_FIELDS}
	if isinstance(value, (list, tuple)):
		return [_normalise(v) for v in value]
	if isinstance(value, float):
		# 10.0 and 10 and "10" must fingerprint the same as the Decimal the server will use.
		return format(Decimal(str(value)).normalize(), "f")
	if isinstance(value, Decimal):
		return format(value.normalize(), "f")
	if isinstance(value, int) and not isinstance(value, bool):
		return str(value)
	return value


def fingerprint(payload: dict) -> str:
	canonical = json.dumps(_normalise(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_replay(stored_fingerprint: str | None, incoming_fingerprint: str) -> str:
	"""`new` when nothing is stored, `replay` for an identical retry, `conflict` otherwise."""
	if stored_fingerprint is None:
		return "new"
	if stored_fingerprint == incoming_fingerprint:
		return "replay"
	return "conflict"
