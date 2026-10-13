# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for pt_bank_ref_match.

All data is synthetic (fake names, no real bank numbers). A fresh UK-chart
company is created by AccountTestInvoicingCommon, so the tests do not depend
on the database's main company.
"""
from odoo import fields
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.pt_bank_ref_match.models.res_company import DEFAULT_REF_REGEX


@tagged("post_install", "-at_install")
class TestBankRefMatch(AccountTestInvoicingCommon):
    chart_template = "uk"
    country_code = "GB"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        # Neutralise the chart's own automatic reconciliation models so only
        # the reference / name logic of this module is exercised.
        cls.env["account.reconcile.model"].search(
            [("company_id", "=", cls.company.id), ("trigger", "=", "auto_reconcile")]
        ).active = False
        cls.bank_journal = cls.env["account.journal"].create(
            {"name": "Test Bank", "type": "bank", "code": "TBNK"}
        )
        cls.partner_jane = cls.env["res.partner"].create({"name": "Jane Sample"})
        cls.partner_alex = cls.env["res.partner"].create({"name": "Alex Example"})
        cls.partner_ona = cls.env["res.partner"].create({"name": "Ona Žemaitė"})
        cls.supplier = cls.env["res.partner"].create(
            {"name": "Fictional Supplies Ltd", "is_company": True}
        )
        cls.no_tax = cls.env["account.tax"]
        cls.StLine = cls.env["account.bank.statement.line"]
        cls.auto_ctx = {"_test_account_reconcile_oca": True}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _invoice(self, amount, partner=None, move_type="out_invoice", post=True, **kw):
        return self._create_invoice_one_line(
            price_unit=amount,
            tax_ids=self.no_tax,
            move_type=move_type,
            partner_id=partner or self.partner_jane,
            post=post,
            **kw,
        )

    def _line(self, amount, payment_ref, auto=False, **kw):
        vals = {
            "journal_id": self.bank_journal.id,
            "date": fields.Date.today(),
            "amount": amount,
            "payment_ref": payment_ref,
        }
        vals.update(kw)
        model = self.StLine.with_context(**self.auto_ctx) if auto else self.StLine
        return model.create(vals)

    @staticmethod
    def _term_line(move):
        return move.line_ids.filtered(
            lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")
        )

    # ------------------------------------------------------------------
    # settings / data
    # ------------------------------------------------------------------
    def test_company_defaults(self):
        self.assertEqual(self.company.pt_ref_match_regex, DEFAULT_REF_REGEX)
        self.assertEqual(self.company.pt_name_match, "suggest")

    def test_settings_related_fields_write_company(self):
        settings = self.env["res.config.settings"].with_company(self.company).create({})
        self.assertEqual(settings.company_id, self.company)
        settings.pt_ref_match_regex = r"ORD-\d+"
        settings.pt_name_match = "auto"
        settings.execute()
        self.assertEqual(self.company.pt_ref_match_regex, r"ORD-\d+")
        self.assertEqual(self.company.pt_name_match, "auto")

    def test_server_action_bound_to_statement_lines(self):
        action = self.env.ref("pt_bank_ref_match.action_pt_auto_match")
        self.assertEqual(action.binding_model_id.model, "account.bank.statement.line")
        self.assertIn("action_pt_auto_match", action.code)

    # ------------------------------------------------------------------
    # reference extraction
    # ------------------------------------------------------------------
    def test_extract_refs_inside_text_and_deduplicated(self):
        line = self._line(
            10.0,
            "Jane SampleS01234 paid INV/2026/00042 and S01234 again",
            narration="also SAJ/2025/0007",
        )
        self.assertEqual(
            line._pt_extract_refs(), ["S01234", "INV/2026/00042", "SAJ/2025/0007"]
        )

    def test_extract_refs_case_insensitive(self):
        line = self._line(10.0, "payment inv/2026/00042")
        self.assertEqual(line._pt_extract_refs(), ["inv/2026/00042"])

    def test_extract_refs_disabled_or_nothing_found(self):
        line = self._line(10.0, "Card payment, no reference here")
        self.assertEqual(line._pt_extract_refs(), [])
        self.company.pt_ref_match_regex = False
        line2 = self._line(10.0, "INV/2026/00042")
        self.assertEqual(line2._pt_extract_refs(), [])

    def test_extract_refs_invalid_regex_logs_and_returns_empty(self):
        self.company.pt_ref_match_regex = r"INV/(\d+"  # unbalanced bracket
        line = self._line(10.0, "INV/2026/00042")
        with self.assertLogs(
            "odoo.addons.pt_bank_ref_match.models.account_bank_statement_line",
            level="WARNING",
        ):
            self.assertEqual(line._pt_extract_refs(), [])

    # ------------------------------------------------------------------
    # counterpart lookup by reference
    # ------------------------------------------------------------------
    def test_find_by_invoice_number_inside_description(self):
        inv = self._invoice(120.0)
        line = self._line(120.0, "FASTER PAYMENT Jane Sample %s" % inv.name)
        self.assertEqual(line._pt_find_counterpart(), self._term_line(inv))

    def test_find_by_payment_reference_glued_to_name(self):
        """Typical UK bank text: order number glued to the payer name."""
        inv = self._invoice(75.0, payment_reference="S01234")
        line = self._line(75.0, "Jane SampleS01234")
        self.assertEqual(line._pt_find_counterpart(), self._term_line(inv))

    def test_find_by_move_ref(self):
        inv = self._invoice(30.0, ref="S04321", payment_reference="SOMETHING-ELSE")
        line = self._line(30.0, "Payment S04321")
        self.assertEqual(line._pt_find_counterpart(), self._term_line(inv))

    def test_no_reference_no_match(self):
        self._invoice(50.0, payment_reference="S01111")
        line = self._line(50.0, "Jane Sample thank you")
        self.assertFalse(line._pt_find_counterpart())

    def test_reference_of_other_document_no_match(self):
        self._invoice(50.0, payment_reference="S01111")
        line = self._line(50.0, "Jane Sample S09999")
        self.assertFalse(line._pt_find_counterpart())

    def test_ambiguous_reference_no_match(self):
        self._invoice(50.0, payment_reference="S05555")
        self._invoice(60.0, payment_reference="S05555", partner=self.partner_alex)
        line = self._line(50.0, "S05555")
        self.assertFalse(line._pt_find_counterpart())

    def test_ambiguous_reference_resolved_by_partner(self):
        self._invoice(50.0, payment_reference="S05555")
        inv_alex = self._invoice(60.0, payment_reference="S05555", partner=self.partner_alex)
        line = self._line(60.0, "S05555", partner_id=self.partner_alex.id)
        self.assertEqual(line._pt_find_counterpart(), self._term_line(inv_alex))

    def test_partner_mismatch_no_match(self):
        self._invoice(50.0, payment_reference="S06666")
        line = self._line(50.0, "S06666", partner_id=self.partner_alex.id)
        self.assertFalse(line._pt_find_counterpart())

    def test_partner_contact_matches_commercial_partner(self):
        company = self.env["res.partner"].create({"name": "Sample Trading Ltd", "is_company": True})
        contact = self.env["res.partner"].create({"name": "Jo Contact", "parent_id": company.id})
        inv = self._invoice(80.0, partner=company, payment_reference="S07777")
        line = self._line(80.0, "S07777", partner_id=contact.id)
        self.assertEqual(line._pt_find_counterpart(), self._term_line(inv))

    def test_direction_must_match(self):
        """Money going out never matches a customer invoice."""
        self._invoice(50.0, payment_reference="S08888")
        line = self._line(-50.0, "Refund S08888")
        self.assertFalse(line._pt_find_counterpart())

    def test_vendor_bill_matched_by_ref_on_outgoing_payment(self):
        bill = self._invoice(
            200.0, partner=self.supplier, move_type="in_invoice", ref="INV/2026/00999"
        )
        line = self._line(-200.0, "To Fictional Supplies INV/2026/00999")
        self.assertEqual(line._pt_find_counterpart(), self._term_line(bill))
        # same text but money coming in: no match (direction)
        line_in = self._line(200.0, "From Fictional Supplies INV/2026/00999")
        self.assertFalse(line_in._pt_find_counterpart())

    def test_vendor_bill_number_matches_default_pattern(self):
        """The default pattern advertises BILL/<year>/<number>. Odoo 19 vendor
        bills are numbered with a monthly sequence (BILL/2026/10/0001); the
        bank description carrying our own bill number must still match."""
        bill = self._invoice(45.0, partner=self.supplier, move_type="in_invoice")
        line = self._line(-45.0, "Payment %s" % bill.name)
        self.assertEqual(
            line._pt_find_counterpart(),
            self._term_line(bill),
            "bill number %r not found by default pattern %r"
            % (bill.name, self.company.pt_ref_match_regex),
        )

    def test_draft_and_paid_documents_ignored(self):
        self._invoice(40.0, payment_reference="S01212", post=False)
        line = self._line(40.0, "S01212")
        self.assertFalse(line._pt_find_counterpart(), "draft invoice must be ignored")

        paid = self._invoice(40.0, payment_reference="S03434")
        self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=paid.ids
        ).create({})._create_payments()
        self.assertEqual(paid.payment_state in ("paid", "in_payment"), True)
        line2 = self._line(40.0, "S03434")
        self.assertFalse(line2._pt_find_counterpart(), "paid invoice must be ignored")

    def test_other_company_ignored(self):
        other = self.setup_other_company(name="Other UK Co")["company"]
        inv = self._create_invoice_one_line(
            price_unit=99.0,
            tax_ids=self.env["account.tax"],
            partner_id=self.partner_jane,
            payment_reference="S02020",
            company_id=other.id,
            journal_id=self.env["account.journal"].search(
                [("company_id", "=", other.id), ("type", "=", "sale")], limit=1
            ).id,
            post=True,
        )
        self.assertEqual(inv.company_id, other)
        line = self._line(99.0, "S02020")
        self.assertFalse(line._pt_find_counterpart())

    def test_zero_amount_line_no_match(self):
        self._invoice(40.0, payment_reference="S01313")
        line = self._line(0.0, "S01313")
        self.assertFalse(line._pt_find_counterpart())

    # ------------------------------------------------------------------
    # automatic reconciliation (hook into OCA auto-reconcile on create)
    # ------------------------------------------------------------------
    def test_auto_reconcile_full_payment(self):
        inv = self._invoice(150.0, payment_reference="S01500")
        line = self._line(150.0, "Jane SampleS01500", auto=True)
        self.assertTrue(line.is_reconciled)
        self.assertIn(inv.payment_state, ("paid", "in_payment"))
        self.assertTrue(self._term_line(inv).reconciled)

    def test_auto_reconcile_partial_payment(self):
        inv = self._invoice(150.0, payment_reference="S01501")
        line = self._line(100.0, "S01501 part 1", auto=True)
        self.assertTrue(line.is_reconciled)
        self.assertEqual(inv.payment_state, "partial")
        self.assertAlmostEqual(inv.amount_residual, 50.0)

    def test_overpayment_left_for_user(self):
        inv = self._invoice(150.0, payment_reference="S01502")
        line = self._line(200.0, "S01502", auto=True)
        self.assertFalse(line.is_reconciled)
        self.assertEqual(inv.payment_state, "not_paid")

    def test_auto_reconcile_without_reference_does_nothing_by_default(self):
        inv = self._invoice(150.0)
        line = self._line(150.0, "Jane Sample monthly", auto=True)
        self.assertFalse(line.is_reconciled)
        self.assertEqual(inv.payment_state, "not_paid")

    def test_auto_reconcile_vendor_bill(self):
        bill = self._invoice(
            60.0, partner=self.supplier, move_type="in_invoice", ref="S07070"
        )
        line = self._line(-60.0, "FICTIONAL SUPPLIES S07070", auto=True)
        self.assertTrue(line.is_reconciled)
        self.assertIn(bill.payment_state, ("paid", "in_payment"))

    # ------------------------------------------------------------------
    # fallback: payer name + exact amount
    # ------------------------------------------------------------------
    def test_name_tokens(self):
        tokens = self.StLine._pt_name_tokens
        self.assertEqual(tokens("EXAMPLE ALEX"), tokens("Alex Example"))
        self.assertEqual(tokens("ZEMAITE ONA"), tokens("Ona Žemaitė"))
        self.assertEqual(tokens("Mr J. Sample 2"), frozenset({"mr", "sample"}))
        self.assertEqual(tokens(False), frozenset())

    def test_name_amount_auto_reconciles(self):
        self.company.pt_name_match = "auto"
        inv = self._invoice(42.5, partner=self.partner_alex)
        line = self._line(42.5, "Faster payment", partner_name="EXAMPLE ALEX", auto=True)
        self.assertTrue(line.is_reconciled)
        self.assertIn(inv.payment_state, ("paid", "in_payment"))

    def test_name_amount_word_order(self):
        self.company.pt_name_match = "auto"
        inv = self._invoice(19.99, partner=self.partner_alex)
        line = self._line(19.99, "Payment", partner_name="EXAMPLE ALEX", auto=True)
        self.assertTrue(line.is_reconciled)
        self.assertIn(inv.payment_state, ("paid", "in_payment"))

    def test_name_amount_accented_bank_text_plain_partner(self):
        self.company.pt_name_match = "auto"
        partner = self.env["res.partner"].create({"name": "Rasa Kalnaite"})
        inv = self._invoice(19.99, partner=partner)
        line = self._line(19.99, "Payment", partner_name="KALNAITĖ RASA", auto=True)
        self.assertTrue(line.is_reconciled)
        self.assertIn(inv.payment_state, ("paid", "in_payment"))

    def test_name_amount_accented_partner_plain_bank_text(self):
        """README: 'Žemaitė' == 'ZEMAITE'. UK bank files strip accents, the
        partner in Odoo keeps them. The candidate search is
        name ilike <longest token without accents>, which only finds the
        accented partner when the PostgreSQL 'unaccent' extension is active
        (not the default for a self-hosted Community database)."""
        self.company.pt_name_match = "auto"
        inv = self._invoice(19.99, partner=self.partner_ona)
        line = self._line(19.99, "Payment", partner_name="ZEMAITE ONA", auto=True)
        self.assertEqual(
            line._pt_payer_partners(),
            self.partner_ona,
            "unaccent extension active: %s" % bool(self.env.registry.has_unaccent),
        )
        self.assertTrue(line.is_reconciled)
        self.assertIn(inv.payment_state, ("paid", "in_payment"))

    def test_name_amount_suggest_prefills_but_does_not_reconcile(self):
        self.company.pt_name_match = "suggest"
        inv = self._invoice(42.5, partner=self.partner_alex)
        line = self._line(42.5, "Faster payment", partner_name="Alex Example", auto=True)
        self.assertFalse(line.is_reconciled)
        self.assertEqual(inv.payment_state, "not_paid")
        data = line._default_reconcile_data()
        other = [d for d in data["data"] if d.get("kind") == "other"]
        self.assertEqual(len(other), 1)
        self.assertEqual(other[0]["id"], self._term_line(inv).id)
        self.assertTrue(data.get("can_reconcile"))
        # the user validates the suggestion
        line.reconcile_data_info = data
        line.reconcile_bank_line()
        self.assertTrue(line.is_reconciled)
        self.assertIn(inv.payment_state, ("paid", "in_payment"))

    def test_reference_suggested_in_widget(self):
        """Overpayment with a reference: not reconciled automatically but the
        invoice is pre-filled for the user (suggest mode)."""
        inv = self._invoice(150.0, payment_reference="S01503")
        line = self._line(200.0, "S01503", auto=True)
        self.assertFalse(line.is_reconciled)
        other = [d for d in line._default_reconcile_data()["data"] if d.get("kind") == "other"]
        self.assertEqual([d["id"] for d in other], self._term_line(inv).ids)

    def test_name_amount_off(self):
        self.company.pt_name_match = "off"
        inv = self._invoice(42.5, partner=self.partner_alex)
        line = self._line(42.5, "Faster payment", partner_name="Alex Example", auto=True)
        self.assertFalse(line.is_reconciled)
        self.assertFalse(line._pt_find_by_name_amount())
        self.assertFalse(
            [d for d in line._default_reconcile_data()["data"] if d.get("kind") == "other"]
        )
        self.assertEqual(inv.payment_state, "not_paid")

    def test_name_amount_single_word_ignored(self):
        self.company.pt_name_match = "auto"
        partner = self.env["res.partner"].create({"name": "Madonna"})
        self._invoice(42.5, partner=partner)
        line = self.StLine.with_context(skip_retrieve_partner=True).create(
            {
                "journal_id": self.bank_journal.id,
                "date": fields.Date.today(),
                "amount": 42.5,
                "payment_ref": "Faster payment",
                "partner_name": "MADONNA",
            }
        )
        self.assertFalse(line.partner_id)
        self.assertFalse(line._pt_payer_partners())
        self.assertFalse(line._pt_find_by_name_amount())

    def test_single_word_surname_never_auto_reconciles(self):
        """README: 'A single-word name is ignored.' But on create the OCA
        module fills partner_id from partner_name with complete_name ILIKE
        '%SMITH%' and takes the first hit; _pt_payer_partners then trusts that
        partner, so in 'auto' mode a bare surname can reconcile against the
        wrong customer's invoice."""
        self.company.pt_name_match = "auto"
        john = self.env["res.partner"].create({"name": "John Smithfake"})
        self.env["res.partner"].create({"name": "Anna Smithfake"})
        inv_john = self._invoice(42.5, partner=john)
        line = self._line(42.5, "Faster payment", partner_name="SMITHFAKE", auto=True)
        self.assertFalse(
            line.is_reconciled,
            "bank line with only a surname was reconciled with %s's invoice "
            "(partner set by OCA: %s)" % (john.name, line.partner_id.name),
        )
        self.assertEqual(inv_john.payment_state, "not_paid")

    def test_guessed_partner_with_full_name_is_used(self):
        """Partner filled by OCA from the payer name, and the payer name is
        exactly that partner's name: the match still works."""
        self.company.pt_name_match = "auto"
        inv = self._invoice(42.5, partner=self.partner_alex)
        line = self._line(42.5, "Faster payment", partner_name="EXAMPLE ALEX")
        if line.partner_id:
            self.assertTrue(line.pt_partner_from_name)
        self.assertEqual(line._pt_find_by_name_amount(), self._term_line(inv))

    def test_partner_changed_by_hand_resets_guess_flag(self):
        john = self.env["res.partner"].create({"name": "John Smithfake"})
        line = self._line(10.0, "Faster payment", partner_name="SMITHFAKE")
        self.assertEqual(line.partner_id, john)
        self.assertTrue(line.pt_partner_from_name)
        line.partner_id = self.partner_alex
        self.assertFalse(line.pt_partner_from_name)
        self.assertEqual(line._pt_payer_partners(), self.partner_alex)

    def test_reference_found_despite_wrong_guessed_partner(self):
        """OCA guessed the wrong partner from a surname; the reference in the
        description still finds the right invoice."""
        john = self.env["res.partner"].create({"name": "John Smithfake"})
        anna = self.env["res.partner"].create({"name": "Anna Smithfake"})
        inv_anna = self._invoice(30.0, partner=anna, payment_reference="S07070")
        line = self._line(30.0, "S07070", partner_name="SMITHFAKE")
        self.assertEqual(line.partner_id, john)
        self.assertEqual(line._pt_find_counterpart(), self._term_line(inv_anna))

    def test_name_amount_mismatch(self):
        self.company.pt_name_match = "auto"
        self._invoice(42.5, partner=self.partner_alex)
        line = self._line(42.0, "Faster payment", partner_name="Alex Example")
        self.assertFalse(line._pt_find_by_name_amount())

    def test_name_amount_two_open_invoices_same_amount(self):
        self.company.pt_name_match = "auto"
        self._invoice(42.5, partner=self.partner_alex)
        self._invoice(42.5, partner=self.partner_alex)
        line = self._line(42.5, "Faster payment", partner_name="Alex Example", auto=True)
        self.assertFalse(line._pt_find_by_name_amount())
        self.assertFalse(line.is_reconciled)

    def test_name_amount_uses_residual(self):
        """Second instalment: the residual (not the total) must equal the amount."""
        self.company.pt_name_match = "auto"
        inv = self._invoice(100.0, partner=self.partner_alex, payment_reference="S04040")
        first = self._line(60.0, "S04040", auto=True)
        self.assertTrue(first.is_reconciled)
        line = self._line(40.0, "rest", partner_name="Alex Example")
        self.assertEqual(line._pt_find_by_name_amount(), self._term_line(inv))

    def test_name_amount_bank_partner_takes_precedence(self):
        self.company.pt_name_match = "auto"
        inv = self._invoice(42.5, partner=self.partner_alex)
        line = self._line(
            42.5, "Faster payment", partner_id=self.partner_alex.id, partner_name="Someone Else"
        )
        self.assertEqual(line._pt_payer_partners(), self.partner_alex)
        self.assertEqual(line._pt_find_by_name_amount(), self._term_line(inv))

    def test_name_amount_homonyms_ambiguous(self):
        self.company.pt_name_match = "auto"
        twin = self.env["res.partner"].create({"name": "Example Alex"})
        self._invoice(42.5, partner=self.partner_alex)
        self._invoice(42.5, partner=twin)
        # "Example, Alex": OCA's partner retrieval finds nobody, tokens match both
        line = self._line(42.5, "Faster payment", partner_name="Example, Alex")
        self.assertFalse(line.partner_id)
        self.assertEqual(len(line._pt_payer_partners()), 2)
        self.assertFalse(line._pt_find_by_name_amount())

    # ------------------------------------------------------------------
    # manual action
    # ------------------------------------------------------------------
    @mute_logger("odoo.addons.pt_bank_ref_match.models.account_bank_statement_line")
    def test_action_pt_auto_match(self):
        inv = self._invoice(25.0, payment_reference="S02525")
        matched = self._line(25.0, "Jane SampleS02525")
        unmatched = self._line(31.0, "unknown payer")
        self.assertFalse(matched.is_reconciled)
        result = (matched | unmatched).action_pt_auto_match()
        self.assertTrue(matched.is_reconciled)
        self.assertFalse(unmatched.is_reconciled)
        self.assertIn(inv.payment_state, ("paid", "in_payment"))
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "success")
        self.assertIn("1 of 2", result["params"]["message"])

        # already reconciled lines are skipped
        result = (matched | unmatched).action_pt_auto_match()
        self.assertIn("0 of 1", result["params"]["message"])
        self.assertEqual(result["params"]["type"], "warning")
