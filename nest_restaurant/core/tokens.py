"""Opaque session tokens and signed QR context.

Guests (client baskets, table ordering, bookings) never get Frappe credentials. They hold a random
token; the server stores only its SHA-256. A table QR carries a signed, expiring *context* (outlet +
table) — it says where the guest is, not what they may do. Authority comes from the visit session the
server creates after validating that context.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time


class TokenError(ValueError):
	pass


def new_token(nbytes: int = 32) -> str:
	return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
	if not token or len(token) > 256:
		raise TokenError("Invalid token")
	return hashlib.sha256(token.encode("utf-8")).hexdigest()


def short_code(length: int = 6) -> str:
	"""Human-readable handoff code without ambiguous characters (no 0/O, 1/I/L)."""
	alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
	return "".join(secrets.choice(alphabet) for _ in range(length))


def _b64(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
	pad = "=" * (-len(text) % 4)
	return base64.urlsafe_b64decode(text + pad)


def sign_context(secret: str, scope: str, fields: dict[str, str], ttl_seconds: int, now: int | None = None) -> str:
	"""`v1.<payload>.<mac>` where payload is `scope|k=v|…|exp=<unix>`; keys sorted, values must not hold `|`."""
	if not secret or len(secret) < 32:
		raise TokenError("Signing secret is not configured")
	issued = int(now if now is not None else time.time())
	parts = [scope]
	for key in sorted(fields):
		value = str(fields[key])
		if "|" in value or "=" in key:
			raise TokenError("Context values cannot contain separators")
		parts.append(f"{key}={value}")
	parts.append(f"exp={issued + int(ttl_seconds)}")
	payload = "|".join(parts).encode("utf-8")
	mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
	return f"v1.{_b64(payload)}.{_b64(mac)}"


def verify_context(secret: str, token: str, scope: str, now: int | None = None) -> dict[str, str]:
	try:
		version, payload_b64, mac_b64 = token.split(".")
		payload = _unb64(payload_b64)
		mac = _unb64(mac_b64)
	except Exception as e:
		raise TokenError("Malformed code") from e
	if version != "v1":
		raise TokenError("Unsupported code version")
	expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
	if not hmac.compare_digest(expected, mac):
		raise TokenError("Code signature is not valid")
	parts = payload.decode("utf-8").split("|")
	if parts[0] != scope:
		raise TokenError("Code is for a different purpose")
	fields = dict(p.split("=", 1) for p in parts[1:])
	exp = int(fields.pop("exp", "0"))
	if exp < int(now if now is not None else time.time()):
		raise TokenError("Code has expired")
	return fields
