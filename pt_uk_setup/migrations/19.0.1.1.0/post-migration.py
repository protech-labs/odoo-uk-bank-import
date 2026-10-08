# Copyright 2026 Pro Technologies Limited
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""1.1.0: Revolut Business mapping, Revolut fee pattern and Revolut ← PayPal
rule. The install hook creates only what is missing, so re-running it on
upgrade adds the new items and leaves existing ones untouched."""
from odoo import SUPERUSER_ID, api

from odoo.addons.pt_uk_setup.hooks import post_init_hook


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    post_init_hook(env)
    # The fee rule already exists in older databases: extend its pattern.
    for rule in env["account.reconcile.model"].search(
        [("name", "=", "Bank & payment provider fees")]
    ):
        if "Revolut Business Fee" not in (rule.match_label_param or ""):
            rule.match_label_param = (rule.match_label_param or "") + "|Revolut Business Fee"
