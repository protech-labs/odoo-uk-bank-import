# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Creates the generic setup for every company that uses the UK chart.

Everything is created only if missing (by name/code), so running it again — or
installing on a database that already has some of it — is safe. Nothing here is
client-specific: supplier rules (hosting, software subscriptions...) and bank journals are added
per client.
"""
import logging

_logger = logging.getLogger(__name__)

SHEET_MAPPINGS = [
    {
        "name": "HSBC UK — Business Internet Banking (CSV)",
        "file_encoding": "utf-8-sig",
        "delimiter": "comma",
        "quotechar": '"',
        "float_thousands_sep": "comma",
        "float_decimal_sep": "dot",
        "timestamp_format": "%d %b %Y",
        "timestamp_column": "Date",
        "amount_type": "simple_value",
        "amount_column": "Amount",
        "balance_column": "Balance",
        "description_column": "Description",
        "notes_column": "Type",
        "skip_empty_lines": True,
    },
    {
        # Wise Business → balance → Statements → Balance statement → CSV
        # (one file and one journal per currency). Date WITH time, otherwise
        # same-day movements are ordered wrongly and the opening balance is off.
        "name": "Wise — Balance statement (CSV)",
        "file_encoding": "utf-8",
        "delimiter": "comma",
        "quotechar": '"',
        "float_thousands_sep": "none",
        "float_decimal_sep": "dot",
        "timestamp_format": "%d-%m-%Y %H:%M:%S.%f",
        "timestamp_column": "Date Time",
        "amount_type": "simple_value",
        "amount_column": "Amount",
        "balance_column": "Running Balance",
        "transaction_id_column": "TransferWise ID",
        "description_column": "Description",
        "reference_column": "Payment Reference",
        "partner_name_column": "Payer Name",
        "notes_column": "Merchant",
        "skip_empty_lines": True,
    },
    {
        # Revolut Business → account → Statement → Excel/CSV, one account
        # (currency) per file. "Total amount" = Amount + Fee (card FX fee), so
        # the running Balance column ties out. Date only, newest first — same
        # as HSBC. Sender name = who paid us (helps name+amount matching).
        "name": "Revolut Business — account statement (CSV)",
        "file_encoding": "utf-8",
        "delimiter": "comma",
        "quotechar": '"',
        "float_thousands_sep": "none",
        "float_decimal_sep": "dot",
        "timestamp_format": "%Y-%m-%d",
        "timestamp_column": "Date completed (Europe/London)",
        "amount_type": "simple_value",
        "amount_column": "Total amount",
        "balance_column": "Balance",
        "transaction_id_column": "ID",
        "description_column": "Description",
        "reference_column": "Reference",
        "partner_name_column": "Sender name",
        "notes_column": "Type",
        "skip_empty_lines": True,
    },
]

CLEARING_ACCOUNTS = [
    ("120090", "PayPal card holds (clearing)", "asset_current"),
]

# (name, trigger, match_label, pattern, account code, journal scope)
# journal scope: None = all bank journals; "paypal" / "wise" = journals whose
# name contains that word.
RULES = [
    ("Bank & payment provider fees", "auto_reconcile", "match_regex",
     r"Non-Sterling Transaction Fee|^PayPal fee|Wise Charges for|Assets service fee|Revolut Business Fee",
     "791000", None),
    ("Interest / cashback", "auto_reconcile", "match_regex",
     r"Interest payment|Card Cashback|Interest or Stocks turned|Debit Card Cashback Bonus",
     "490000", None),
    ("PayPal → bank (withdrawal)", "auto_reconcile", "match_regex",
     r"User Initiated Withdrawal|General Withdrawal", "122001", "paypal"),
    ("Bank ← PayPal (transfer in)", "auto_reconcile", "match_regex",
     r"Received money from PAYPAL|PAYPAL.*(WITHDRAW|TRANSFER)", "122001", "wise"),
    ("Revolut ← PayPal (top-up)", "auto_reconcile", "match_regex",
     r"Money added from PAYPAL", "122001", "revolut"),
    ("PayPal card holds", "auto_reconcile", "match_regex",
     r"Account Hold for Open Authorisation|Reversal of General Account Hold",
     "120090", "paypal"),
    ("Wages (suggest)", "manual", "match_regex", r"\bWAGES\b|SALARY", "222000", None),
    ("HMRC PAYE / NIC (suggest)", "manual", "match_regex", r"HMRC.*(PAYE|NIC|CUMBERNAULD|SHIPLEY)", "221000", None),
]


def _account(env, company, code):
    return env["account.account"].with_company(company).search(
        [("code", "=", code), ("company_ids", "in", company.id)], limit=1
    )


def _setup_company(env, company):
    Account = env["account.account"].with_company(company)
    for code, name, acc_type in CLEARING_ACCOUNTS:
        if not _account(env, company, code):
            Account.create(
                {"code": code, "name": name, "account_type": acc_type,
                 "company_ids": [(6, 0, [company.id])]}
            )

    # VAT-inclusive purchase tax for bank rules of VAT-registered clients:
    # the bank amount is gross, so the rule must split it into net + VAT.
    Tax = env["account.tax"].with_company(company)
    if not Tax.search([("company_id", "=", company.id), ("name", "=", "20% G (incl.)")]):
        base = Tax.search(
            [("company_id", "=", company.id), ("type_tax_use", "=", "purchase"),
             ("amount_type", "=", "percent"), ("amount", "=", 20),
             ("price_include_override", "!=", "tax_included")],
            limit=1,
        )
        if base:
            base.copy({"name": "20% G (incl.)", "price_include_override": "tax_included"})

    Journal = env["account.journal"].with_company(company)
    Model = env["account.reconcile.model"].with_company(company)
    for name, trigger, ml, pattern, code, scope in RULES:
        if Model.search([("company_id", "=", company.id), ("name", "=", name)]):
            continue
        account = _account(env, company, code)
        if not account:
            _logger.warning("pt_uk_setup: account %s missing in %s, rule %s skipped",
                            code, company.name, name)
            continue
        vals = {
            "name": name,
            "company_id": company.id,
            "trigger": trigger,
            "match_label": ml,
            "match_label_param": pattern,
            "line_ids": [(0, 0, {"account_id": account.id, "amount_type": "percentage",
                                 "amount_string": "100", "label": name})],
        }
        if scope:
            journals = Journal.search(
                [("company_id", "=", company.id), ("type", "=", "bank"),
                 ("name", "ilike", scope)]
            )
            if journals:
                vals["match_journal_ids"] = [(6, 0, journals.ids)]
        Model.create(vals)


def post_init_hook(env):
    Mapping = env["account.statement.import.sheet.mapping"]
    for vals in SHEET_MAPPINGS:
        if not Mapping.search([("name", "=", vals["name"])]):
            Mapping.create(vals)
    for company in env["res.company"].search([("chart_template", "=", "uk")]):
        _setup_company(env, company)
