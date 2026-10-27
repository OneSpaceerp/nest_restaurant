# Copyright (c) 2026, Nest Software Development (nsdLabs) and contributors
# For license information, please see license.txt
"""Pure, framework-free domain logic shared by Nest POS and Nest Restaurant.

This package is the source of truth. `tools/vendor_shared.py` copies it into each app
(`<app>/core/`) so neither app imports the other. Nothing here imports frappe.
"""

__version__ = "0.1.0"
