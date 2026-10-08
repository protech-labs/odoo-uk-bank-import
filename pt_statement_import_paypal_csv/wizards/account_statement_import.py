# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import csv
import io
from datetime import datetime

from odoo import models
from odoo.exceptions import UserError

PAYPAL_HEADER = ("Date", "Time", "Time zone", "Name", "Type", "Status", "Currency", "Gross", "Fee", "Net")


def _amount(value):
    value = (value or "").strip().replace(",", "")
    return float(value) if value else 0.0


class AccountStatementImport(models.TransientModel):
    _inherit = "account.statement.import"

    def _pt_paypal_rows(self, data_file):
        """Rows of a PayPal activity CSV, or None if the file is something else."""
        try:
            text = data_file.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
        reader = csv.DictReader(io.StringIO(text))
        if tuple(reader.fieldnames or ())[: len(PAYPAL_HEADER)] != PAYPAL_HEADER:
            return None
        if "Balance" not in reader.fieldnames or "Transaction ID" not in reader.fieldnames:
            return None
        return list(reader)

    def _parse_file(self, data_file):
        if getattr(self, "sheet_mapping_id", False):
            return super()._parse_file(data_file)
        rows = self._pt_paypal_rows(data_file)
        if rows is None:
            return super()._parse_file(data_file)

        # Lines that really move the balance. "Memo" = authorisation holds:
        # informational only. Status is NOT a filter: a 'Refused' hold
        # cancellation still changes the balance in PayPal's own figures.
        rows = [r for r in rows if (r.get("Balance Impact") or "").strip() != "Memo"]
        if not rows:
            raise UserError(self.env._("The PayPal file contains no balance movements."))

        journal = self.env["account.journal"].browse(self.env.context.get("journal_id"))
        if journal:
            currency = (journal.currency_id or journal.company_id.currency_id).name
        else:
            currency = rows[0]["Currency"]
        rows = [r for r in rows if r["Currency"] == currency]
        if not rows:
            raise UserError(
                self.env._("The PayPal file has no %(cur)s movements.", cur=currency)
            )

        def row_date(r):
            return datetime.strptime(r["Date"].strip(), "%d/%m/%Y").date()

        rows.sort(key=lambda r: (row_date(r), r.get("Time", "")))
        transactions = []
        for r in rows:
            txid = r["Transaction ID"].strip()
            date = row_date(r)
            name = (r.get("Name") or "").strip()
            label = " / ".join(
                filter(
                    None,
                    [
                        (r.get("Subject") or r.get("Item Title") or "").strip(),
                        (r.get("Invoice Number") or "").strip(),
                    ],
                )
            )
            payment_ref = " — ".join(filter(None, [r["Type"].strip(), name, label])) or txid
            transactions.append(
                {
                    "date": date,
                    "payment_ref": payment_ref,
                    "amount": _amount(r["Gross"]),
                    "partner_name": name or False,
                    "ref": txid,
                    "unique_import_id": "PP-%s" % txid,
                    "narration": " | ".join(
                        filter(None, [r.get("From Email Address"), r.get("Note")])
                    )
                    or False,
                }
            )
            fee = _amount(r["Fee"])
            if fee:
                transactions.append(
                    {
                        "date": date,
                        "payment_ref": "PayPal fee — %s" % (name or txid),
                        "amount": fee,
                        "partner_name": "PayPal",
                        "ref": txid,
                        "unique_import_id": "PP-%s-FEE" % txid,
                    }
                )
        # Odoo orders statement lines by date, then by sequence REVERSED
        # (higher sequence = earlier, see account.bank.statement.line
        # internal_index). The OCA importer numbers lines 1, 2, 3... in list
        # order, which put each fee before its own payment and later payments
        # of a day before earlier ones (odd running balance). Number them in
        # reverse so the chronological order of the file is kept.
        for seq, vals in enumerate(reversed(transactions), start=1):
            vals["sequence"] = seq
        first, last = rows[0], rows[-1]
        balance_start = round(_amount(first["Balance"]) - _amount(first["Net"]), 2)
        statement = {
            "name": "PayPal %s %s – %s"
            % (currency, row_date(first).strftime("%d.%m.%Y"), row_date(last).strftime("%d.%m.%Y")),
            "date": row_date(last),
            "balance_start": balance_start,
            "balance_end_real": _amount(last["Balance"]),
            "transactions": transactions,
        }
        return currency, None, [statement]
