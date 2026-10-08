# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pt_ref_match_regex = fields.Char(
        related="company_id.pt_ref_match_regex", readonly=False
    )
    pt_name_match = fields.Selection(related="company_id.pt_name_match", readonly=False)
