# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Pro Technologies — UK small business setup",
    "summary": "Bank import mappings (HSBC, Wise, Revolut Business), generic UK bank reconciliation "
    "rules (fees, PayPal holds and transfers, interest), VAT-inclusive purchase tax",
    "version": "19.0.1.2.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "author": "Pro Technologies Limited",
    "website": "https://www.pro-technologies.co.uk",
    "depends": [
        "l10n_uk",
        "account_statement_import_sheet_file",
        "pt_bank_ref_match",
        "pt_statement_import_paypal_csv",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
