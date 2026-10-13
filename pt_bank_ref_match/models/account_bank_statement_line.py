# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging
import re
import unicodedata

from odoo import fields, models
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

# Letters that NFKD does not split into base letter + accent.
_EXTRA_FOLD = {"ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ø": "o", "Ø": "o", "ß": "s"}


def _fold_char(char):
    if char in _EXTRA_FOLD:
        return _EXTRA_FOLD[char]
    base = "".join(
        c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c)
    )
    return base if len(base) == 1 else char


# translate() tables for SQL: accented Latin letters -> plain lower-case letter.
# Done in SQL instead of relying on the PostgreSQL "unaccent" extension, which
# is not installed on a default self-hosted database.
_SQL_FOLD_FROM = ""
_SQL_FOLD_TO = ""
for _code in range(0x00C0, 0x0250):
    _char = chr(_code)
    _plain = _fold_char(_char)
    if _plain != _char and _plain.isascii() and _plain.isalpha():
        _SQL_FOLD_FROM += _char
        _SQL_FOLD_TO += _plain.lower()
for _char, _plain in _EXTRA_FOLD.items():
    if _char not in _SQL_FOLD_FROM:
        _SQL_FOLD_FROM += _char
        _SQL_FOLD_TO += _plain


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    pt_partner_from_name = fields.Boolean(
        string="Partner guessed from payer name",
        copy=False,
        help="Set when account_reconcile_oca filled the partner from the payer "
        "name on import (not from the bank account number). Reset when the "
        "partner is changed.",
    )

    def write(self, vals):
        if "partner_id" in vals and "pt_partner_from_name" not in vals:
            vals = dict(vals, pt_partner_from_name=False)
        return super().write(vals)

    def _retrieve_partner(self):
        """Remember which lines got their partner from the payer name."""
        if self.env.context.get("skip_retrieve_partner"):
            return super()._retrieve_partner()
        self.env.flush_all()
        todo = self.filtered(
            lambda line: not line.partner_id
            and not line.is_reconciled
            and line.partner_name
        )
        by_account = set()
        with_account = todo.filtered("account_number")
        if with_account:
            query = with_account._get_retrieve_partner_account_query()
            self.env.cr.execute(query.select(SQL.identifier(self._table, "id")))
            by_account = {row[0] for row in self.env.cr.fetchall()}
        res = super()._retrieve_partner()
        guessed = todo.filtered(
            lambda line: line.partner_id and line.id not in by_account
        )
        if guessed:
            guessed.write({"pt_partner_from_name": True})
        return res

    # ------------------------------------------------------------------
    # Reference extraction and lookup
    # ------------------------------------------------------------------
    def _pt_extract_refs(self):
        """Return the distinct references found in the bank description."""
        self.ensure_one()
        pattern = self.company_id.pt_ref_match_regex
        text = " ".join(filter(None, [self.payment_ref, self.narration and str(self.narration)]))
        if not pattern or not text:
            return []
        try:
            found = [m.group(0) for m in re.finditer(pattern, text, re.IGNORECASE)]
        except re.error:
            _logger.warning("Invalid bank reference pattern: %s", pattern)
            return []
        return list(dict.fromkeys(found))

    def _pt_find_counterpart(self):
        """One open receivable/payable line whose entry carries one of the
        references, same direction as the bank line. Empty if none or ambiguous."""
        self.ensure_one()
        AML = self.env["account.move.line"]
        refs = self._pt_extract_refs()
        if not refs or not self.amount:
            return AML
        ref_domain = []
        for ref in refs:
            ref_domain += [
                ("move_id.payment_reference", "=ilike", ref),
                ("move_id.name", "=ilike", ref),
                ("move_id.ref", "=ilike", ref),
            ]
        ref_domain = ["|"] * (len(ref_domain) - 1) + ref_domain
        domain = [
            ("company_id", "=", self.company_id.id),
            ("parent_state", "=", "posted"),
            ("reconciled", "=", False),
            ("account_id.reconcile", "=", True),
            ("account_id.account_type", "in", ("asset_receivable", "liability_payable")),
            ("balance", ">" if self.amount > 0 else "<", 0),
        ] + ref_domain
        if self.partner_id and not self.pt_partner_from_name:
            domain.append(
                (
                    "partner_id.commercial_partner_id",
                    "=",
                    self.partner_id.commercial_partner_id.id,
                )
            )
        lines = AML.search(domain, limit=2)
        return lines if len(lines) == 1 else AML

    # ------------------------------------------------------------------
    # Fallback: payer name + exact amount (no reference in the description)
    # ------------------------------------------------------------------
    @staticmethod
    def _pt_name_tokens(name):
        """Lower-case words without accents, order-independent:
        'EXAMPLE ALEX' == 'Alex Example', 'Žemaitė' == 'ZEMAITE'."""
        if not name:
            return frozenset()
        text = "".join(_fold_char(c) for c in name).lower()
        return frozenset(w for w in re.findall(r"[^\W\d_]+", text) if len(w) > 1)

    def _pt_payer_partners(self):
        """Commercial partners that can be the payer of this bank line."""
        self.ensure_one()
        Partner = self.env["res.partner"]
        tokens = self._pt_name_tokens(self.partner_name)
        if self.partner_id:
            commercial = self.partner_id.commercial_partner_id
            # A partner set by hand or found by bank account number is trusted.
            # One that account_reconcile_oca guessed from the payer name (loose
            # ILIKE, first hit) is trusted only if the name really is theirs.
            if not self.pt_partner_from_name or (
                len(tokens) >= 2
                and tokens
                in (
                    self._pt_name_tokens(self.partner_id.name),
                    self._pt_name_tokens(commercial.name),
                )
            ):
                return commercial
        if len(tokens) < 2:  # a single word is too weak to identify a person
            return Partner
        longest = max(tokens, key=len)
        self.env["res.partner"].flush_model(["name"])
        self.env.cr.execute(
            "SELECT id FROM res_partner "
            "WHERE lower(translate(name, %s, %s)) LIKE %s LIMIT 50",
            (_SQL_FOLD_FROM, _SQL_FOLD_TO, "%" + longest + "%"),
        )
        candidates = Partner.with_context(active_test=False).browse(
            [row[0] for row in self.env.cr.fetchall()]
        ).exists()
        return candidates.filtered(
            lambda p: self._pt_name_tokens(p.name) == tokens
        ).commercial_partner_id

    def _pt_find_by_name_amount(self):
        self.ensure_one()
        AML = self.env["account.move.line"]
        if self.company_id.pt_name_match in (False, "off") or not self.amount:
            return AML
        partners = self._pt_payer_partners()
        if not partners:
            return AML
        currency = self.journal_id.currency_id or self.company_id.currency_id
        lines = AML.search(
            [
                ("company_id", "=", self.company_id.id),
                ("parent_state", "=", "posted"),
                ("reconciled", "=", False),
                ("account_id.reconcile", "=", True),
                (
                    "account_id.account_type",
                    "in",
                    ("asset_receivable", "liability_payable"),
                ),
                ("partner_id.commercial_partner_id", "in", partners.ids),
                ("currency_id", "=", currency.id),
                ("balance", ">" if self.amount > 0 else "<", 0),
            ]
        )
        lines = lines.filtered(
            lambda l: currency.is_zero(l.amount_residual_currency - self.amount)
        )
        return lines if len(lines) == 1 else AML

    def _pt_counterpart_data(self, counterpart):
        """reconcile_data_info: bank (liquidity) line + the counterpart."""
        self.ensure_one()
        liquidity_lines, _suspense, _other = self._seek_for_lines()
        data = []
        aux_id = 1
        for line in liquidity_lines:
            aux_id, lines = self._get_reconcile_line(
                line, "liquidity", reconcile_auxiliary_id=aux_id, move=True
            )
            data += lines
        aux_id, lines = self._get_reconcile_line(
            counterpart,
            "other",
            is_counterpart=True,
            max_amount=self.amount_currency or self.amount,
            move=True,
        )
        data += lines
        return self._recompute_suspense_line(data, aux_id, self.manual_reference)

    def _default_reconcile_data(self):
        """'Suggest' mode: an unreconciled line opens with the matching invoice
        already filled in; the user only presses Validate."""
        res = super()._default_reconcile_data()
        if (
            len(self) == 1
            and not self.is_reconciled
            and self.company_id.pt_name_match in ("suggest", "auto")
            and not any(
                line.get("kind") == "other" for line in res.get("data", [])
            )
        ):
            counterpart = self._pt_find_counterpart() or self._pt_find_by_name_amount()
            if counterpart:
                res = self._pt_counterpart_data(counterpart)
        return res

    # ------------------------------------------------------------------
    # Hook into the OCA auto-reconcile (runs on import and on demand)
    # ------------------------------------------------------------------
    def _do_auto_reconcile_invoices(self):
        remaining, done = super()._do_auto_reconcile_invoices()
        matched = self.browse()
        for record in remaining:
            counterpart = record._pt_find_counterpart()
            if not counterpart and record.company_id.pt_name_match == "auto":
                counterpart = record._pt_find_by_name_amount()
            if not counterpart:
                continue
            record.reconcile_data_info = record._pt_counterpart_data(counterpart)
            if record.reconcile_data_info.get("can_reconcile"):
                matched |= record
        return remaining - matched, done | matched

    # ------------------------------------------------------------------
    # Manual trigger (list action)
    # ------------------------------------------------------------------
    def action_pt_auto_match(self):
        """Re-run reconciliation models and reference matching on the selected
        lines that are not reconciled yet. Work-in-progress (unsaved) matching
        on those lines is recomputed."""
        todo = self.filtered(lambda rec: not rec.is_reconciled)
        todo._do_auto_reconcile(True)
        matched = len(todo.filtered("is_reconciled"))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Auto-match"),
                "message": self.env._(
                    "%(done)s of %(total)s line(s) reconciled.",
                    done=matched,
                    total=len(todo),
                ),
                "type": "success" if matched else "warning",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
