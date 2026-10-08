# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Import PayPal Activity CSV (gross + fee lines)",
    "summary": "Import the PayPal 'Activity download' CSV: one line per payment "
    "at gross amount plus a separate PayPal fee line; holds (Memo) skipped",
    "version": "19.0.1.0.1",
    "category": "Accounting",
    "license": "AGPL-3",
    "author": "Pro Technologies Limited",
    "website": "https://www.pro-technologies.co.uk",
    "depends": ["account_statement_import_file"],
    "data": ["views/account_statement_import.xml"],
    "installable": True,
}
