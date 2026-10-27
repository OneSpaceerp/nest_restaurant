"""Reservation slots and capacity. The service takes a row lock on the outlet before calling
`check_capacity`, so two simultaneous bookings cannot both see the last free seats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


class BookingError(ValueError):
	pass


@dataclass
class Window:
	opens: str  # "HH:MM"
	closes: str
	slot_minutes: int = 30
	stay_minutes: int = 90


def _at(day: datetime, hhmm: str) -> datetime:
	hh, mm = hhmm.split(":")
	return day.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)


def validate_slot(start: datetime, window: Window, now: datetime, lead_minutes: int = 30, horizon_days: int = 60):
	opens, closes = _at(start, window.opens), _at(start, window.closes)
	if closes <= opens:
		closes += timedelta(days=1)
	if not (opens <= start and start + timedelta(minutes=window.stay_minutes) <= closes):
		raise BookingError("That time is outside opening hours")
	if (start - opens).total_seconds() % (window.slot_minutes * 60):
		raise BookingError("Choose one of the listed times")
	if start < now + timedelta(minutes=lead_minutes):
		raise BookingError("That time is too soon to book online")
	if start > now + timedelta(days=horizon_days):
		raise BookingError("That date is too far ahead")


def overlaps(a_start: datetime, a_minutes: int, b_start: datetime, b_minutes: int) -> bool:
	return a_start < b_start + timedelta(minutes=b_minutes) and b_start < a_start + timedelta(minutes=a_minutes)


def check_capacity(
	party: int, start: datetime, stay_minutes: int, existing: list[tuple[datetime, int, int]], seats: int,
	max_party: int,
) -> int:
	"""`existing` is (start, stay_minutes, party). Returns seats left after this booking or raises."""
	if party < 1 or party > max_party:
		raise BookingError(f"Online bookings are for 1 to {max_party} guests")
	used = sum(p for s, m, p in existing if overlaps(start, stay_minutes, s, m))
	left = seats - used - party
	if left < 0:
		raise BookingError("We're full at that time; try another time")
	return left
