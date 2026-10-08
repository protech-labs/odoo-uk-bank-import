# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Bank Statement: Match by Invoice Reference",
    "summary": "Auto-match bank statement lines to open invoices/bills "
    "by a reference found anywhere in the bank description (S01234, "
    "SAJ/2026/0042, INV/2026/0042...)",
    "version": "19.0.1.1.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "author": "Pro Technologies Limited",
    "website": "https://www.pro-technologies.co.uk",
    "depends": ["account_reconcile_oca"],
    "data": [
        "data/ir_actions_server.xml",
        "views/res_config_settings.xml",
    ],
    "installable": True,
}
