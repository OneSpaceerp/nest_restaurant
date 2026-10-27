"""Staff PINs: salted PBKDF2 hashes, weak-PIN rejection and lockout policy. No plain-text storage."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

ITERATIONS = 210_000
MIN_LENGTH, MAX_LENGTH = 4, 8


class PinError(ValueError):
	pass


def validate_new_pin(pin: str) -> str:
	pin = (pin or "").strip()
	if not pin.isdigit() or not (MIN_LENGTH <= len(pin) <= MAX_LENGTH):
		raise PinError(f"A PIN must be {MIN_LENGTH}-{MAX_LENGTH} digits.")
	if len(set(pin)) == 1:
		raise PinError("Choose a PIN that is not a single repeated digit.")
	digits = [int(c) for c in pin]
	steps = {b - a for a, b in zip(digits, digits[1:], strict=False)}
	if steps in ({1}, {-1}):
		raise PinError("Choose a PIN that is not a simple sequence.")
	return pin


def hash_pin(pin: str, salt: str | None = None, iterations: int = ITERATIONS) -> str:
	salt = salt or secrets.token_hex(16)
	digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt), iterations)
	return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
	try:
		algo, iterations, salt, digest = stored.split("$")
	except (AttributeError, ValueError):
		return False
	if algo != "pbkdf2_sha256":
		return False
	candidate = hash_pin(pin or "", salt, int(iterations)).split("$")[3]
	return hmac.compare_digest(candidate, digest)


def lockout_after_failure(
	failed_attempts: int, now: datetime, max_attempts: int = 5, base_minutes: int = 5
) -> tuple[int, datetime | None]:
	"""Return the new failure count and, once the limit is reached, when the lock lifts.

	Each further failure past the limit doubles the lock (5, 10, 20 … capped at 24 h).
	"""
	failed = failed_attempts + 1
	if failed < max_attempts:
		return failed, None
	over = failed - max_attempts
	minutes = min(base_minutes * (2**over), 24 * 60)
	return failed, now + timedelta(minutes=minutes)


def is_locked(locked_until: datetime | None, now: datetime) -> bool:
	return bool(locked_until and locked_until > now)
