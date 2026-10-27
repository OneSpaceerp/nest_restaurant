"""Frappe-facing services shared by Nest apps. Vendored into each app as `<app>/kit/`.

Modules import the owning app's identity with `from ..appspec import SPEC` and pure logic with
`from ..core import …`. Nothing here imports the *other* Nest app.
"""
