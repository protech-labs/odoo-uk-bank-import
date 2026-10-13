# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for pt_uk_setup (install hook + 19.0.1.1.0 migration).

The test company is a fresh UK-chart company created by
AccountTestInvoicingCommon; the hook is called explicitly on it. Synthetic
data only."""
import base64
import importlib.util
import os

from odoo import fields
from odoo.modules.module import get_module_path
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.pt_uk_setup import hooks
from odoo.addons.pt_uk_setup.hooks import RULES, SHEET_MAPPINGS, post_init_hook


def _load_migration():
    path = os.path.join(
        get_module_path("pt_uk_setup"), "migrations", "19.0.1.1.0", "post-migration.py"
    )
    spec = importlib.util.spec_from_file_location("pt_uk_setup_post_migration_1_1_0", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RULE_NAMES = [r[0] for r in RULES]


@tagged("post_install", "-at_install")
class TestUkSetup(AccountTestInvoicingCommon):
    chart_template = "uk"
    country_code = "GB"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        Journal = cls.env["account.journal"]
        cls.j_paypal = Journal.create({"name": "PayPal GBP", "type": "bank", "code": "TPP"})
        cls.j_wise = Journal.create({"name": "Wise GBP", "type": "bank", "code": "TWI"})
        cls.j_revolut = Journal.create(
            {"name": "Revolut Business", "type": "bank", "code": "TRV"}
        )
        cls.j_hsbc = Journal.create({"name": "HSBC Current", "type": "bank", "code": "THS"})
        # The hook runs at install time on the companies that existed then;
        # run it for the test company (created after install).
        # Odoo runs install hooks as superuser.
        cls.su_env = cls.env(su=True)
        post_init_hook(cls.su_env)
        cls.Rule = cls.env["account.reconcile.model"]

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _rules(self, company=None):
        return self.Rule.sudo().search([("company_id", "=", (company or self.company).id),
                                        ("name", "in", RULE_NAMES)])

    def _rule(self, name, company=None):
        return self.Rule.sudo().search([("company_id", "=", (company or self.company).id),
                                        ("name", "=", name)])

    def _account(self, code, company=None):
        return hooks._account(self.su_env, company or self.company, code)

    def _snapshot(self):
        c = self.company
        return (
            self.env["account.statement.import.sheet.mapping"].search_count([]),
            self.env["account.account"].search_count([("company_ids", "in", c.id)]),
            self.env["account.tax"].search_count([("company_id", "=", c.id)]),
            self.Rule.search_count([("company_id", "=", c.id)]),
        )

    # ------------------------------------------------------------------
    # result of the hook
    # ------------------------------------------------------------------
    def test_sheet_mappings_created(self):
        Mapping = self.env["account.statement.import.sheet.mapping"]
        for vals in SHEET_MAPPINGS:
            mapping = Mapping.search([("name", "=", vals["name"])])
            self.assertEqual(len(mapping), 1, vals["name"])
            for key, value in vals.items():
                self.assertEqual(mapping[key], value, "%s.%s" % (vals["name"], key))

    def test_clearing_account_created(self):
        account = self._account("120090")
        self.assertTrue(account)
        self.assertEqual(account.account_type, "asset_current")
        self.assertEqual(account.name, "PayPal card holds (clearing)")

    def test_vat_inclusive_purchase_tax(self):
        Tax = self.env["account.tax"]
        incl = Tax.search([("company_id", "=", self.company.id), ("name", "=", "20% G (incl.)")])
        self.assertEqual(len(incl), 1)
        self.assertEqual(incl.type_tax_use, "purchase")
        self.assertEqual(incl.amount, 20)
        self.assertEqual(incl.price_include_override, "tax_included")
        base = Tax.search([("company_id", "=", self.company.id), ("name", "=", "20% G")])
        self.assertTrue(base)
        self.assertNotEqual(base.price_include_override, "tax_included")

        # same VAT box tags as the base tax (box 7 base, box 4 tax)
        def tags(tax):
            return sorted(
                (rl.document_type, rl.repartition_type, tuple(sorted(rl.tag_ids.mapped("name"))))
                for rl in tax.repartition_line_ids
            )
        self.assertEqual(tags(incl), tags(base))
        # 120.00 gross -> 100.00 net + 20.00 VAT
        res = incl.compute_all(120.0)
        self.assertAlmostEqual(res["total_excluded"], 100.0)
        self.assertAlmostEqual(res["taxes"][0]["amount"], 20.0)

    def test_all_rules_created(self):
        rules = self._rules()
        self.assertEqual(
            sorted(rules.mapped("name")), sorted(RULE_NAMES),
            "missing rules: %s" % (set(RULE_NAMES) - set(rules.mapped("name"))),
        )

    def test_rule_values(self):
        for name, trigger, match_label, pattern, code, scope in RULES:
            rule = self._rule(name)
            self.assertEqual(len(rule), 1, name)
            self.assertEqual(rule.trigger, trigger, name)
            self.assertEqual(rule.match_label, match_label, name)
            self.assertEqual(rule.match_label_param, pattern, name)
            self.assertEqual(len(rule.line_ids), 1, name)
            line = rule.line_ids
            self.assertEqual(line.account_id, self._account(code), name)
            self.assertEqual(line.amount_type, "percentage", name)
            self.assertAlmostEqual(line.amount, 100.0, msg=name)

    def test_rule_journal_scope(self):
        expected = {None: self.env["account.journal"], "paypal": self.j_paypal,
                    "wise": self.j_wise, "revolut": self.j_revolut}
        for name, _t, _m, _p, _c, scope in RULES:
            self.assertEqual(self._rule(name).match_journal_ids, expected[scope], name)

    def test_liquidity_transfer_account_is_122001(self):
        """Three rules post to 122001: it must be the company's liquidity
        transfer account of the UK chart."""
        self.assertEqual(self._account("122001"), self.company.transfer_account_id)

    def test_non_uk_company_untouched(self):
        generic = self.env["res.company"].search([("chart_template", "!=", "uk")], limit=1)
        if not generic:
            self.skipTest("no non-UK company in this database")
        self.assertFalse(self._rules(generic))
        self.assertFalse(self._account("120090", generic))

    # ------------------------------------------------------------------
    # idempotency
    # ------------------------------------------------------------------
    def test_hook_idempotent(self):
        before = self._snapshot()
        post_init_hook(self.su_env)
        post_init_hook(self.su_env)
        self.assertEqual(self._snapshot(), before)

    def test_hook_keeps_user_changes(self):
        rule = self._rule("Interest / cashback")
        rule.match_label_param = "Interest payment only"
        post_init_hook(self.su_env)
        self.assertEqual(rule.match_label_param, "Interest payment only")
        self.assertEqual(len(self._rule("Interest / cashback")), 1)

    def test_hook_recreates_deleted_items(self):
        self._rule("PayPal card holds").unlink()
        self.env["account.tax"].search(
            [("company_id", "=", self.company.id), ("name", "=", "20% G (incl.)")]
        ).unlink()
        before = self._snapshot()
        post_init_hook(self.su_env)
        after = self._snapshot()
        self.assertEqual(after[2], before[2] + 1)  # tax
        self.assertEqual(after[3], before[3] + 1)  # rule
        self.assertEqual(len(self._rule("PayPal card holds")), 1)

    def test_missing_account_skips_rule_with_warning(self):
        company = self.setup_other_company(name="UK Co without 490000")["company"]
        self._account("490000", company).code = "490999"
        with self.assertLogs("odoo.addons.pt_uk_setup.hooks", level="WARNING") as logs:
            post_init_hook(self.su_env)
        self.assertTrue(any("490000" in m for m in logs.output))
        self.assertFalse(self._rule("Interest / cashback", company))
        self.assertEqual(len(self._rules(company)), len(RULES) - 1)

    def test_company_without_scoped_journals_gets_unscoped_rules(self):
        """README: journal-scoped rules pick journals by name at install
        time; with no PayPal/Wise/Revolut journal the rule applies to every
        bank journal of that company."""
        company = self.setup_other_company(name="UK Co no journals")["company"]
        post_init_hook(self.su_env)
        for name, _t, _m, _p, _c, scope in RULES:
            rule = self._rule(name, company)
            self.assertEqual(len(rule), 1, name)
            self.assertFalse(rule.match_journal_ids, name)

    # ------------------------------------------------------------------
    # migration 19.0.1.1.0
    # ------------------------------------------------------------------
    def test_migration_from_1_0(self):
        """Simulate a 1.0 database: no Revolut mapping / rule, old fee pattern."""
        migration = _load_migration()
        old_pattern = (
            r"Non-Sterling Transaction Fee|^PayPal fee|Wise Charges for|Assets service fee"
        )
        self.env["account.statement.import.sheet.mapping"].search(
            [("name", "=", "Revolut Business — account statement (CSV)")]
        ).unlink()
        self._rule("Revolut ← PayPal (top-up)").unlink()
        fee_rule = self._rule("Bank & payment provider fees")
        fee_rule.match_label_param = old_pattern
        self.env.flush_all()

        migration.migrate(self.env.cr, "19.0.1.0.0")
        self.env.invalidate_all()

        self.assertEqual(
            self.env["account.statement.import.sheet.mapping"].search_count(
                [("name", "=", "Revolut Business — account statement (CSV)")]
            ),
            1,
        )
        revolut_rule = self._rule("Revolut ← PayPal (top-up)")
        self.assertEqual(len(revolut_rule), 1)
        self.assertEqual(revolut_rule.match_journal_ids, self.j_revolut)
        self.assertEqual(fee_rule.match_label_param, old_pattern + "|Revolut Business Fee")

        # running it again changes nothing
        before = self._snapshot()
        migration.migrate(self.env.cr, "19.0.1.0.0")
        self.env.invalidate_all()
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(fee_rule.match_label_param.count("Revolut Business Fee"), 1)

    # ------------------------------------------------------------------
    # patterns, evaluated by PostgreSQL like account_reconcile_oca does (~*)
    # ------------------------------------------------------------------
    def _pg_match(self, text, pattern):
        self.env.cr.execute("SELECT %s ~* %s", (text, pattern))
        return self.env.cr.fetchone()[0]

    def test_rule_patterns_in_postgres(self):
        samples = {
            "Bank & payment provider fees": [
                "Non-Sterling Transaction Fee 2.75", "PayPal fee — Jane Sample",
                "Wise Charges for: 123", "Revolut Business Fee - Grow plan",
            ],
            "Interest / cashback": ["Interest payment", "Debit Card Cashback Bonus"],
            "PayPal → bank (withdrawal)": ["General Withdrawal", "User Initiated Withdrawal"],
            "Bank ← PayPal (transfer in)": [
                "Received money from PAYPAL EUROPE", "PAYPAL PPWDL TRANSFER 1234",
            ],
            "Revolut ← PayPal (top-up)": ["Money added from PAYPAL"],
            "PayPal card holds": [
                "Account Hold for Open Authorisation", "Reversal of General Account Hold",
            ],
            "HMRC PAYE / NIC (suggest)": ["HMRC CUMBERNAULD 123PA00012345"],
        }
        patterns = {r[0]: r[3] for r in RULES}
        for name, texts in samples.items():
            for text in texts:
                self.assertTrue(self._pg_match(text, patterns[name]), "%s / %r" % (name, text))
        # a payment of a customer called Mr Fee must not become a bank fee
        self.assertFalse(
            self._pg_match("Jane Sample PayPal fee refund", patterns["Bank & payment provider fees"])
        )

    def test_wages_pattern_in_postgres(self):
        r"""'\bWAGES\b' is a word boundary in Python, but in PostgreSQL
        regular expressions (used by account_reconcile_oca to apply rules)
        '\b' is a backspace, so 'WAGES' never matches. Only bites if the
        'Wages (suggest)' rule is switched to automatic."""
        pattern = dict((r[0], r[3]) for r in RULES)["Wages (suggest)"]
        self.assertTrue(self._pg_match("WAGES OCT JANE SAMPLE", pattern))

    # ------------------------------------------------------------------
    # integration: rules applied by account_reconcile_oca
    # ------------------------------------------------------------------
    def _auto_line(self, journal, amount, label):
        return self.env["account.bank.statement.line"].with_context(
            _test_account_reconcile_oca=True
        ).create(
            {"journal_id": journal.id, "date": fields.Date.today(),
             "amount": amount, "payment_ref": label}
        )

    def _counter_accounts(self, line):
        liquidity, suspense, other = line._seek_for_lines()
        return other.account_id

    def test_paypal_fee_line_reconciled_to_bank_fees(self):
        line = self._auto_line(self.j_paypal, -3.20, "PayPal fee — Jane Sample")
        self.assertTrue(line.is_reconciled)
        self.assertEqual(self._counter_accounts(line), self._account("791000"))

    def test_revolut_fee_and_topup(self):
        fee = self._auto_line(self.j_revolut, -25.0, "Revolut Business Fee - Grow plan")
        self.assertTrue(fee.is_reconciled)
        self.assertEqual(self._counter_accounts(fee), self._account("791000"))
        topup = self._auto_line(self.j_revolut, 500.0, "Money added from PAYPAL")
        self.assertTrue(topup.is_reconciled)
        self.assertEqual(self._counter_accounts(topup), self._account("122001"))

    def test_scoped_rule_not_applied_on_other_journal(self):
        line = self._auto_line(self.j_hsbc, 500.0, "Money added from PAYPAL")
        self.assertFalse(line.is_reconciled)

    def test_paypal_hold_to_clearing(self):
        line = self._auto_line(self.j_paypal, -50.0, "Account Hold for Open Authorisation")
        self.assertTrue(line.is_reconciled)
        self.assertEqual(self._counter_accounts(line), self._account("120090"))

    def test_manual_rules_not_applied_automatically(self):
        line = self._auto_line(self.j_hsbc, -1500.0, "SALARY JANE SAMPLE")
        self.assertFalse(line.is_reconciled)

    # ------------------------------------------------------------------
    # integration: the three sheet mappings read sample files
    # ------------------------------------------------------------------
    def _import_with_mapping(self, journal, mapping_name, content):
        mapping = self.env["account.statement.import.sheet.mapping"].search(
            [("name", "=", mapping_name)]
        )
        wiz = self.env["account.statement.import"].with_context(journal_id=journal.id).create(
            {"statement_filename": "sample.csv",
             "statement_file": base64.b64encode(content),
             "sheet_mapping_id": mapping.id}
        )
        wiz.import_file_button()
        return self.env["account.bank.statement"].search(
            [("journal_id", "=", journal.id)], order="id desc", limit=1
        )

    def test_hsbc_mapping_sample(self):
        content = (
            "Date,Type,Description,Amount,Balance\n"
            '03 Oct 2026,DD,FICTIONAL ENERGY LTD,-120.00,"1,330.00"\n'
            '02 Oct 2026,CR,JANE SAMPLE S01234,"1,250.00","1,450.00"\n'
            "02 Oct 2026,DR,Non-Sterling Transaction Fee,-0.50,200.00\n"
            "01 Oct 2026,CR,ALEX EXAMPLE,100.50,200.50\n"
        ).encode("utf-8-sig")
        st = self._import_with_mapping(self.j_hsbc, SHEET_MAPPINGS[0]["name"], content)
        self.assertEqual(len(st.line_ids), 4)
        self.assertAlmostEqual(st.balance_start, 100.00)
        self.assertAlmostEqual(st.balance_end_real, 1330.00)
        self.assertAlmostEqual(st.balance_end, st.balance_end_real)

    def test_wise_mapping_sample(self):
        content = (
            "TransferWise ID,Date,Date Time,Amount,Currency,Description,"
            "Payment Reference,Running Balance,Payer Name,Merchant\n"
            "TRANSFER-1003,03-10-2026,03-10-2026 16:00:00.000,-2.00,GBP,"
            "Wise Charges for: TRANSFER-1002,,348.00,,\n"
            "TRANSFER-1002,03-10-2026,03-10-2026 09:30:00.500,250.00,GBP,"
            "Received money from Jane Sample,S01234,350.00,Jane Sample,\n"
            "CARD-1001,01-10-2026,01-10-2026 12:00:00.000,-10.00,GBP,"
            "Card transaction,,100.00,,Fictional Cafe\n"
        ).encode()
        st = self._import_with_mapping(self.j_wise, SHEET_MAPPINGS[1]["name"], content)
        self.assertEqual(len(st.line_ids), 3)
        self.assertAlmostEqual(st.balance_start, 110.00)
        self.assertAlmostEqual(st.balance_end_real, 348.00)
        self.assertAlmostEqual(st.balance_end, st.balance_end_real)
        received = st.line_ids.filtered(lambda l: l.amount == 250.0)
        self.assertEqual(received.partner_name, "Jane Sample")

    def test_revolut_mapping_sample(self):
        content = (
            "Date started (UTC),Date completed (Europe/London),ID,Type,Description,"
            "Reference,Sender name,Amount,Fee,Total amount,Balance\n"
            "2026-10-02,2026-10-02,id-3,FEE,Revolut Business Fee,,,-25.00,0.00,-25.00,575.00\n"
            "2026-10-02,2026-10-02,id-2,TRANSFER,Money added from PAYPAL,,,500.00,0.00,500.00,600.00\n"
            "2026-10-01,2026-10-01,id-1,TRANSFER,Payment from Alex Example,S04321,"
            "Alex Example,100.00,0.00,100.00,100.00\n"
        ).encode()
        st = self._import_with_mapping(self.j_revolut, SHEET_MAPPINGS[2]["name"], content)
        self.assertEqual(len(st.line_ids), 3)
        self.assertAlmostEqual(st.balance_start, 0.0)
        self.assertAlmostEqual(st.balance_end_real, 575.00)
        self.assertAlmostEqual(st.balance_end, st.balance_end_real)
