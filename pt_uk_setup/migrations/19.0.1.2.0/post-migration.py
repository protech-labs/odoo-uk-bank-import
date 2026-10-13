# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""1.2.0: the Wages rule pattern used \\b, which PostgreSQL regular expressions
(how account_reconcile_oca applies rules) read as a backspace, so it never
matched. Replace it where it is still the original pattern."""
from odoo import SUPERUSER_ID, api

OLD = r"\bWAGES\b|SALARY"
NEW = r"(^|\W)WAGES(\W|$)|SALARY"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["account.reconcile.model"].search(
        [("name", "=", "Wages (suggest)"), ("match_label_param", "=", OLD)]
    ).match_label_param = NEW
