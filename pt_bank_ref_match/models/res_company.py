# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import fields, models

DEFAULT_REF_REGEX = r"SAJ/\d{4}/\d{3,}|INV/\d{4}/\d{3,}|BILL/\d{4}/\d{3,}|S\d{5}"


class ResCompany(models.Model):
    _inherit = "res.company"

    pt_ref_match_regex = fields.Char(
        string="Bank reference pattern",
        default=DEFAULT_REF_REGEX,
        help="Regular expression used to find invoice / order references "
        "inside the bank statement description. Every match is looked up "
        "in the payment reference, number and reference of open posted "
        "journal entries. Leave empty to disable.",
    )

    pt_name_match = fields.Selection(
        [
            ("off", "Off"),
            ("suggest", "Suggest (pre-fill, user validates)"),
            ("auto", "Reconcile automatically"),
        ],
        string="Match bank lines by payer name and amount",
        default="suggest",
        help="When the bank description has no reference: look for the payer "
        "(by the bank partner, or by the payer name with words in any order) "
        "and exactly one open invoice/bill of that partner for the same amount "
        "in the same currency.",
    )

