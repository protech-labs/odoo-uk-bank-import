# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Many banks export statements newest first and with a date but no time
(Revolut Business, HSBC UK). The OCA parser sorts lines by date with a stable
sort, so movements on the same day keep the file's reversed order: the first
line is no longer the oldest movement, the opening balance is computed from
the wrong row and the running balance is off.

Fix: if the file runs newest first, turn it round before the parser sorts.
Files that are already oldest first are left as they are."""
from odoo import models


class AccountStatementImportSheetParser(models.TransientModel):
    _inherit = "account.statement.import.sheet.parser"

    def _parse_rows(self, mapping, currency_code, data, columns):
        lines = super()._parse_rows(mapping, currency_code, data, columns)
        if len(lines) > 1 and lines[0]["timestamp"] > lines[-1]["timestamp"]:
            lines.reverse()
        return lines
