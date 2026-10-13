# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the PayPal activity CSV parser. Synthetic data only."""
import base64
import csv
import io
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

HEADER = [
    "Date", "Time", "Time zone", "Name", "Type", "Status", "Currency",
    "Gross", "Fee", "Net", "From Email Address", "To Email Address",
    "Transaction ID", "Item Title", "Reference Txn ID", "Invoice Number",
    "Balance", "Subject", "Note", "Balance Impact",
]


def row(d, t, name, typ, status, cur, gross, fee, net, txid, balance, impact,
        email="", item="", invoice="", subject="", note=""):
    return {
        "Date": d, "Time": t, "Time zone": "Europe/London", "Name": name,
        "Type": typ, "Status": status, "Currency": cur, "Gross": gross,
        "Fee": fee, "Net": net, "From Email Address": email,
        "To Email Address": "shop@example.invalid", "Transaction ID": txid,
        "Item Title": item, "Reference Txn ID": "", "Invoice Number": invoice,
        "Balance": balance, "Subject": subject, "Note": note,
        "Balance Impact": impact,
    }


# Opening balance 1,000.00 GBP. Rows deliberately NOT in chronological order.
R1 = row("01/10/2026", "09:15:00", "Jane Sample", "Express Checkout Payment",
         "Completed", "GBP", "100.00", "-3.20", "96.80", "1TEST0000000001A",
         "1,096.80", "Credit", email="jane@example.invalid",
         item="Subscription 12m", invoice="S01234", note="thanks")
R2 = row("01/10/2026", "14:00:00", "Alex Example", "Express Checkout Payment",
         "Completed", "GBP", "1,250.00", "-36.55", "1,213.45", "1TEST0000000002B",
         "2,310.25", "Credit", email="alex@example.invalid", subject="Website build")
R3_MEMO = row("02/10/2026", "10:00:00", "Shop Fictional", "General Authorization",
              "Pending", "GBP", "-50.00", "0.00", "-50.00", "1TEST0000000003C",
              "2,310.25", "Memo")
R4_EUR = row("02/10/2026", "11:00:00", "Eva Muster", "Express Checkout Payment",
             "Completed", "EUR", "20.00", "-0.90", "19.10", "1TEST0000000004D",
             "19.10", "Credit")
R5_REFUND = row("03/10/2026", "08:00:00", "Jane Sample", "Payment Refund",
                "Completed", "GBP", "-100.00", "2.90", "-97.10", "1TEST0000000005E",
                "2,213.15", "Debit", invoice="S01234")
R6_WITHDRAW = row("03/10/2026", "12:00:00", "", "General Withdrawal", "Completed",
                  "GBP", "-2,000.00", "0.00", "-2,000.00", "1TEST0000000006F",
                  "213.15", "Debit")
R7_HOLD = row("03/10/2026", "12:05:00", "", "Reversal of General Account Hold",
              "Refused", "GBP", "50.00", "", "50.00", "1TEST0000000007G",
              "263.15", "Credit")

FILE_ROWS = [R2, R1, R5_REFUND, R3_MEMO, R4_EUR, R7_HOLD, R6_WITHDRAW]


def make_csv(rows, header=HEADER, bom=True):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8-sig" if bom else "utf-8")


@tagged("post_install", "-at_install")
class TestPaypalCsv(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.gbp = cls.env.ref("base.GBP")
        cls.gbp.active = True
        cls.eur = cls.env.ref("base.EUR")
        cls.eur.active = True
        cls.journal = cls.env["account.journal"].create(
            {"name": "PayPal GBP", "type": "bank", "code": "PPGB",
             "currency_id": cls.gbp.id}
        )
        cls.journal_eur = cls.env["account.journal"].create(
            {"name": "PayPal EUR", "type": "bank", "code": "PPEU",
             "currency_id": cls.eur.id}
        )
        cls.Wizard = cls.env["account.statement.import"]

    def _wizard(self, data, journal=None):
        journal = journal or self.journal
        return self.Wizard.with_context(journal_id=journal.id).create(
            {"statement_filename": "paypal.csv",
             "statement_file": base64.b64encode(data)}
        )

    def _import(self, data, journal=None):
        wiz = self._wizard(data, journal)
        wiz.import_file_button()
        return self.env["account.bank.statement"].search(
            [("journal_id", "=", (journal or self.journal).id)], order="id desc", limit=1
        )

    def _parse(self, data, journal=None):
        wiz = self._wizard(data, journal)
        return wiz.with_context(journal_id=(journal or self.journal).id)._parse_file(data)

    @staticmethod
    def _chrono(statement):
        return statement.line_ids.sorted("internal_index")

    # ------------------------------------------------------------------
    # detection
    # ------------------------------------------------------------------
    def test_detects_paypal_file(self):
        wiz = self._wizard(make_csv(FILE_ROWS))
        self.assertEqual(len(wiz._pt_paypal_rows(make_csv(FILE_ROWS))), 7)
        self.assertEqual(len(wiz._pt_paypal_rows(make_csv(FILE_ROWS, bom=False))), 7)

    def test_rejects_other_files(self):
        wiz = self._wizard(b"x")
        self.assertIsNone(wiz._pt_paypal_rows(b"Date,Amount,Description\n01/10/2026,1,x\n"))
        # same columns in another order
        swapped = [HEADER[1], HEADER[0]] + HEADER[2:]
        self.assertIsNone(wiz._pt_paypal_rows(make_csv([R1], header=swapped)))
        # Balance / Transaction ID columns missing
        no_balance = [h for h in HEADER if h != "Balance"]
        self.assertIsNone(wiz._pt_paypal_rows(make_csv([R1], header=no_balance)))
        no_txid = [h for h in HEADER if h != "Transaction ID"]
        self.assertIsNone(wiz._pt_paypal_rows(make_csv([R1], header=no_txid)))
        # not UTF-8
        self.assertIsNone(wiz._pt_paypal_rows("Date,Time,é".encode("latin-1")))

    def test_other_file_falls_back_to_standard_chain(self):
        data = b"Date,Amount,Description\n01/10/2026,1,x\n"
        with self.assertRaisesRegex(UserError, "not supported"):
            self._wizard(data).import_file_button()

    def test_sheet_mapping_bypasses_paypal_parser(self):
        if "sheet_mapping_id" not in self.Wizard._fields:
            self.skipTest("account_statement_import_sheet_file not installed")
        mapping = self.env["account.statement.import.sheet.mapping"].create(
            {"name": "test mapping", "timestamp_format": "%d/%m/%Y",
             "timestamp_column": "Date", "amount_type": "simple_value",
             "amount_column": "Gross", "description_column": "Name",
             "float_thousands_sep": "comma", "float_decimal_sep": "dot",
             "delimiter": "comma", "file_encoding": "utf-8-sig"}
        )
        wiz = self._wizard(make_csv([R1]))
        wiz.sheet_mapping_id = mapping
        currency, _acc, stmts = wiz.with_context(journal_id=self.journal.id)._parse_file(
            make_csv([R1])
        )
        # the generic sheet parser ran: one line, no separate fee line
        self.assertEqual(len(stmts[0]["transactions"]), 1)

    # ------------------------------------------------------------------
    # parsing
    # ------------------------------------------------------------------
    def test_parse_values(self):
        currency, account_number, stmts = self._parse(make_csv(FILE_ROWS))
        self.assertEqual(currency, "GBP")
        self.assertIsNone(account_number)
        self.assertEqual(len(stmts), 1)
        st = stmts[0]
        self.assertEqual(st["name"], "PayPal GBP 01.10.2026 – 03.10.2026")
        self.assertEqual(st["date"], date(2026, 10, 3))
        self.assertAlmostEqual(st["balance_start"], 1000.00)
        self.assertAlmostEqual(st["balance_end_real"], 263.15)
        tx = st["transactions"]
        self.assertEqual(
            [(t["unique_import_id"], t["amount"]) for t in tx],
            [
                ("PP-1TEST0000000001A", 100.00),
                ("PP-1TEST0000000001A-FEE", -3.20),
                ("PP-1TEST0000000002B", 1250.00),
                ("PP-1TEST0000000002B-FEE", -36.55),
                ("PP-1TEST0000000005E", -100.00),
                ("PP-1TEST0000000005E-FEE", 2.90),
                ("PP-1TEST0000000006F", -2000.00),
                ("PP-1TEST0000000007G", 50.00),
            ],
        )
        pay = tx[0]
        self.assertEqual(
            pay["payment_ref"],
            "Express Checkout Payment — Jane Sample — Subscription 12m / S01234",
        )
        self.assertEqual(pay["partner_name"], "Jane Sample")
        self.assertEqual(pay["ref"], "1TEST0000000001A")
        self.assertEqual(pay["narration"], "jane@example.invalid | thanks")
        self.assertEqual(pay["date"], date(2026, 10, 1))
        fee = tx[1]
        self.assertEqual(fee["payment_ref"], "PayPal fee — Jane Sample")
        self.assertEqual(fee["partner_name"], "PayPal")
        self.assertEqual(fee["ref"], "1TEST0000000001A")
        # Subject used when there is no Item Title
        self.assertEqual(
            tx[2]["payment_ref"], "Express Checkout Payment — Alex Example — Website build"
        )
        # rows without a payer name
        self.assertEqual(tx[6]["payment_ref"], "General Withdrawal")
        self.assertFalse(tx[6]["partner_name"])
        self.assertFalse(tx[6]["narration"])
        # sum of lines ties out with the balances
        self.assertAlmostEqual(
            st["balance_start"] + sum(t["amount"] for t in tx), st["balance_end_real"]
        )

    def test_sequence_reversed_for_chronological_display(self):
        _c, _a, stmts = self._parse(make_csv(FILE_ROWS))
        seqs = [t["sequence"] for t in stmts[0]["transactions"]]
        self.assertEqual(seqs, list(range(len(seqs), 0, -1)))

    def test_memo_and_foreign_currency_rows_skipped(self):
        _c, _a, stmts = self._parse(make_csv(FILE_ROWS))
        ids = {t["unique_import_id"] for t in stmts[0]["transactions"]}
        self.assertNotIn("PP-1TEST0000000003C", ids)  # Memo
        self.assertNotIn("PP-1TEST0000000004D", ids)  # EUR

    def test_eur_journal_takes_only_eur_rows(self):
        currency, _a, stmts = self._parse(make_csv(FILE_ROWS), journal=self.journal_eur)
        self.assertEqual(currency, "EUR")
        tx = stmts[0]["transactions"]
        self.assertEqual([t["amount"] for t in tx], [20.00, -0.90])
        self.assertAlmostEqual(stmts[0]["balance_start"], 0.0)
        self.assertAlmostEqual(stmts[0]["balance_end_real"], 19.10)

    def test_no_journal_uses_currency_of_first_row(self):
        wiz = self._wizard(make_csv([R4_EUR, R1]))
        currency, _a, stmts = wiz.with_context(journal_id=False)._parse_file(
            make_csv([R4_EUR, R1])
        )
        self.assertEqual(currency, "EUR")
        self.assertEqual(len(stmts[0]["transactions"]), 2)

    def test_only_memo_rows_raises(self):
        with self.assertRaisesRegex(UserError, "no balance movements"):
            self._parse(make_csv([R3_MEMO]))

    def test_no_rows_in_journal_currency_raises(self):
        with self.assertRaisesRegex(UserError, "no GBP movements"):
            self._parse(make_csv([R4_EUR]))

    def test_zero_or_empty_fee_gives_no_fee_line(self):
        _c, _a, stmts = self._parse(make_csv([R6_WITHDRAW, R7_HOLD]))
        self.assertEqual(len(stmts[0]["transactions"]), 2)
        self.assertFalse(
            [t for t in stmts[0]["transactions"] if t["unique_import_id"].endswith("-FEE")]
        )

    # ------------------------------------------------------------------
    # full import through the wizard
    # ------------------------------------------------------------------
    def test_import_creates_balanced_statement(self):
        statement = self._import(make_csv(FILE_ROWS))
        self.assertEqual(len(statement.line_ids), 8)
        self.assertAlmostEqual(statement.balance_start, 1000.00)
        self.assertAlmostEqual(statement.balance_end_real, 263.15)
        self.assertAlmostEqual(statement.balance_end, 263.15)
        self.assertTrue(statement.is_complete)
        self.assertEqual(self.journal.bank_statements_source, "file_import_oca")
        self.assertTrue(statement.attachment_ids)

    def test_import_keeps_file_order_payment_then_fee(self):
        """Changelog 19.0.1.0.1: payment first, then its fee, earlier payments
        of a day before later ones; running balance follows PayPal."""
        statement = self._import(make_csv(FILE_ROWS))
        lines = self._chrono(statement)
        self.assertEqual(
            lines.mapped("payment_ref"),
            [
                "Express Checkout Payment — Jane Sample — Subscription 12m / S01234",
                "PayPal fee — Jane Sample",
                "Express Checkout Payment — Alex Example — Website build",
                "PayPal fee — Alex Example",
                "Payment Refund — Jane Sample — S01234",
                "PayPal fee — Jane Sample",
                "General Withdrawal",
                "Reversal of General Account Hold",
            ],
        )
        self.assertEqual(
            [round(b, 2) for b in lines.mapped("running_balance")],
            [1100.00, 1096.80, 2346.80, 2310.25, 2210.25, 2213.15, 213.15, 263.15],
        )

    def test_reimport_same_file_is_refused(self):
        self._import(make_csv(FILE_ROWS))
        with self.assertRaisesRegex(UserError, "already imported"):
            self._import(make_csv(FILE_ROWS))

    def test_overlapping_file_imports_only_new_rows(self):
        first = self._import(make_csv([R1, R2]))
        self.assertEqual(len(first.line_ids), 4)
        second = self._import(make_csv([R1, R2, R5_REFUND]))
        self.assertNotEqual(first, second)
        self.assertEqual(len(second.line_ids), 2)
        # opening balance of the new statement = closing balance of the first
        self.assertAlmostEqual(second.balance_start, first.balance_end_real)
        self.assertAlmostEqual(second.balance_end, second.balance_end_real)

    def test_import_into_wrong_currency_journal_refused(self):
        """A file with only EUR rows imported into the GBP journal."""
        with self.assertRaises(UserError):
            self._import(make_csv([R4_EUR]))
