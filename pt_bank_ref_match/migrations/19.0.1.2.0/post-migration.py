# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""1.2.0: the default reference pattern also accepts Odoo 19 monthly numbers
(BILL/2026/10/0001). Companies still on the old default get the new one; a
pattern changed by hand is left alone."""
from odoo import SUPERUSER_ID, api

from odoo.addons.pt_bank_ref_match.models.res_company import (
    DEFAULT_REF_REGEX,
    OLD_DEFAULT_REF_REGEX,
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["res.company"].search(
        [("pt_ref_match_regex", "=", OLD_DEFAULT_REF_REGEX)]
    ).pt_ref_match_regex = DEFAULT_REF_REGEX
