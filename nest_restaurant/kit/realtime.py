"""Scoped realtime. Events go to a document room (`doc:<doctype>/<name>`), which Frappe only lets a
client join after a read-permission check, and are published after commit so a listener never sees a
change that later rolls back. Payloads carry a version; clients re-fetch on gaps or reconnect."""

from __future__ import annotations

import frappe

from ..appspec import SPEC


def to_register(register: str, event: str, payload: dict) -> None:
	frappe.publish_realtime(
		SPEC.event(event), payload, doctype=SPEC.dt("Register"), docname=register, after_commit=True
	)


def to_doc(doctype: str, name: str, event: str, payload: dict) -> None:
	frappe.publish_realtime(SPEC.event(event), payload, doctype=doctype, docname=name, after_commit=True)


def to_user(user: str, event: str, payload: dict) -> None:
	frappe.publish_realtime(SPEC.event(event), payload, user=user, after_commit=True)
