# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Many banks export statements newest first and with a date but no time
(Revolut Business, HSBC UK). The OCA parser sorts lines by date with a stable
sort, so movements on the same day keep the file's reversed order: the first
line is no longer the oldest movement, the opening balance is computed from
the wrong row and the running balance is off.

Fix:
1. If the file runs newest first, turn it round before the parser sorts.
   Direction comes from the dates; when the file covers a single day it comes
   from the balance column (newest first: balance - amount = next row's
   balance). Files that are already oldest first are left as they are.
2. Number the transactions in reverse. Odoo orders statement lines by date,
   then by sequence REVERSED (higher sequence = earlier); the OCA importer
   would number them 1, 2, 3... and show same-day movements upside down."""
from odoo import models
from odoo.tools import float_is_zero


class AccountStatementImportSheetParser(models.TransientModel):
    _inherit = "account.statement.import.sheet.parser"

    @staticmethod
    def _pt_balances_chain(lines):
        """True if each row's balance follows from the previous row."""
        if any(line.get("balance") is None for line in lines):
            return False
        return all(
            float_is_zero(
                prev["balance"] + line["amount"] - line["balance"], precision_digits=2
            )
            for prev, line in zip(lines, lines[1:])
        )

    def _pt_newest_first(self, lines):
        first, last = lines[0]["timestamp"], lines[-1]["timestamp"]
        if first != last:
            return first > last
        return not self._pt_balances_chain(lines) and self._pt_balances_chain(
            lines[::-1]
        )

    def _parse_rows(self, mapping, currency_code, data, columns):
        lines = super()._parse_rows(mapping, currency_code, data, columns)
        if len(lines) > 1 and self._pt_newest_first(lines):
            lines.reverse()
        return lines

    def parse(self, data_file, mapping, filename):
        currency_code, account_number, statements = super().parse(
            data_file, mapping, filename
        )
        for statement in statements:
            transactions = statement.get("transactions") or []
            for seq, vals in enumerate(reversed(transactions), start=1):
                vals["sequence"] = seq
        return currency_code, account_number, statements
