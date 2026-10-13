# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for pt_statement_import_sheet_order. Synthetic data only."""
import base64

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

HEADER = "Date,Description,Amount,Balance\n"

# Opening balance 500.00. Movements (oldest -> newest):
#   01 Oct  +100.00  -> 600.00
#   02 Oct   -20.00  -> 580.00
#   02 Oct   +50.00  -> 630.00
#   02 Oct    -5.00  -> 625.00
#   03 Oct  +10.00   -> 635.00
OLDEST_FIRST = [
    ("2026-10-01", "Payment from Jane Sample", "100.00", "600.00"),
    ("2026-10-02", "Card Fictional Cafe", "-20.00", "580.00"),
    ("2026-10-02", "Payment from Alex Example", "50.00", "630.00"),
    ("2026-10-02", "Bank fee", "-5.00", "625.00"),
    ("2026-10-03", "Interest", "10.00", "635.00"),
]


def csv_bytes(rows):
    return (HEADER + "".join("%s,%s,%s,%s\n" % r for r in rows)).encode()


@tagged("post_install", "-at_install")
class TestSheetOrder(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.env["account.journal"].create(
            {"name": "Test Revolut", "type": "bank", "code": "TREV",
             "currency_id": cls.env.company.currency_id.id}
        )
        cls.mapping = cls.env["account.statement.import.sheet.mapping"].create(
            {
                "name": "Test newest-first bank",
                "file_encoding": "utf-8",
                "delimiter": "comma",
                "quotechar": '"',
                "float_thousands_sep": "none",
                "float_decimal_sep": "dot",
                "timestamp_format": "%Y-%m-%d",
                "timestamp_column": "Date",
                "amount_type": "simple_value",
                "amount_column": "Amount",
                "balance_column": "Balance",
                "description_column": "Description",
            }
        )
        cls.Parser = cls.env["account.statement.import.sheet.parser"]

    def _parse(self, rows, mapping=None):
        return self.Parser.with_context(journal_id=self.journal.id).parse(
            csv_bytes(rows), mapping or self.mapping, "statement.csv"
        )

    def _import(self, rows):
        wiz = self.env["account.statement.import"].with_context(
            journal_id=self.journal.id
        ).create(
            {
                "statement_filename": "statement.csv",
                "statement_file": base64.b64encode(csv_bytes(rows)),
                "sheet_mapping_id": self.mapping.id,
            }
        )
        wiz.import_file_button()
        return self.env["account.bank.statement"].search(
            [("journal_id", "=", self.journal.id)], order="id desc", limit=1
        )

    def _labels(self, stmt_vals):
        return [t["payment_ref"] for t in stmt_vals["transactions"]]

    # ------------------------------------------------------------------
    def test_newest_first_file_is_reversed(self):
        _cur, _acc, stmts = self._parse(list(reversed(OLDEST_FIRST)))
        st = stmts[0]
        self.assertEqual(self._labels(st), [r[1] for r in OLDEST_FIRST])
        self.assertAlmostEqual(float(st["balance_start"]), 500.00)
        self.assertAlmostEqual(float(st["balance_end_real"]), 635.00)

    def test_oldest_first_file_untouched(self):
        _cur, _acc, stmts = self._parse(OLDEST_FIRST)
        st = stmts[0]
        self.assertEqual(self._labels(st), [r[1] for r in OLDEST_FIRST])
        self.assertAlmostEqual(float(st["balance_start"]), 500.00)
        self.assertAlmostEqual(float(st["balance_end_real"]), 635.00)

    def test_parse_rows_override_direct(self):
        """The override only looks at the first and last timestamp of what
        the OCA parser returns; super() is mocked to isolate it."""
        from datetime import datetime
        from unittest.mock import patch

        from odoo.addons.account_statement_import_sheet_file.wizard import (
            account_statement_import_sheet_parser as oca_parser,
        )

        def mk(*days):
            return [{"timestamp": datetime(2026, 10, d), "n": i} for i, d in enumerate(days)]

        cases = [
            (mk(3, 2, 2, 1), [3, 2, 1, 0]),  # newest first -> reversed
            (mk(1, 2, 2, 3), [0, 1, 2, 3]),  # oldest first -> untouched
            (mk(2, 2, 2), [0, 1, 2]),  # one day -> untouched
            (mk(5), [0]),  # single line
            ([], []),  # empty
        ]
        for parsed, expected in cases:
            with patch.object(
                oca_parser.AccountStatementImportSheetParser,
                "_parse_rows",
                return_value=list(parsed),
            ):
                lines = self.Parser._parse_rows(self.mapping, "GBP", None, None)
            self.assertEqual([l["n"] for l in lines], expected)

    def test_single_row(self):
        _cur, _acc, stmts = self._parse(OLDEST_FIRST[:1])
        self.assertEqual(len(stmts[0]["transactions"]), 1)
        self.assertAlmostEqual(float(stmts[0]["balance_start"]), 500.00)

    def test_newest_first_import_balanced_and_running_balance(self):
        statement = self._import(list(reversed(OLDEST_FIRST)))
        self.assertAlmostEqual(statement.balance_start, 500.00)
        self.assertAlmostEqual(statement.balance_end_real, 635.00)
        self.assertAlmostEqual(statement.balance_end, 635.00)
        self.assertTrue(statement.is_complete)

    def test_newest_first_import_running_balance_within_day(self):
        """The module docstring says that without the fix 'the running
        balance is off'. After the import the same-day lines must show in
        bank order so the running balance matches the bank's Balance column.
        (pt_statement_import_paypal_csv solves the same issue by setting
        'sequence' in reverse; the OCA importer numbers lines 1, 2, 3... and
        Odoo shows a higher sequence first within a date.)"""
        statement = self._import(list(reversed(OLDEST_FIRST)))
        lines = statement.line_ids.sorted("internal_index")
        self.assertEqual(
            [round(b, 2) for b in lines.mapped("running_balance")],
            [600.00, 580.00, 630.00, 625.00, 635.00],
        )

    def test_same_day_only_newest_first_file(self):
        """Daily export (all movements on one day), newest first. First and
        last row have the same date, so the module does not detect the
        reversed order and the opening balance comes from the wrong row."""
        same_day = OLDEST_FIRST[1:4]  # three movements on 02 Oct
        _cur, _acc, stmts = self._parse(list(reversed(same_day)))
        st = stmts[0]
        self.assertAlmostEqual(
            float(st["balance_start"]),
            600.00,
            msg="opening balance of a newest-first single-day file",
        )
        self.assertEqual(self._labels(st), [r[1] for r in same_day])
