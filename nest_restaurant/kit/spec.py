"""Per-app identity. Every kit module reads names from the app's `appspec.SPEC`, never literals,
so the same code serves `Nest POS …` and `Nest Restaurant …` documents without sharing any."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AppSpec:
	app: str  # python package, e.g. nest_pos
	prefix: str  # DocType prefix, e.g. "Nest POS"
	field_prefix: str  # custom-field prefix on ERPNext documents, e.g. nest_pos
	route: str  # staff PWA route, e.g. /nest-pos
	desk_page: str  # Desk page name, e.g. nest-pos
	roles: dict = field(default_factory=dict)  # cashier/supervisor/manager (+ waiter/kitchen)
	modules: tuple = ()  # Module Defs in modules.txt order; the first owns custom fields
	extra_invoice_fields: tuple = ()  # app-specific custom fields on Sales/POS Invoice

	def dt(self, suffix: str) -> str:
		return f"{self.prefix} {suffix}"

	def fld(self, suffix: str) -> str:
		return f"{self.field_prefix}_{suffix}"

	def event(self, name: str) -> str:
		return f"{self.field_prefix}:{name}"

	@property
	def staff_roles(self) -> list[str]:
		return list(self.roles.values())

	def role(self, key: str) -> str:
		return self.roles[key]
