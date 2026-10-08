# pt_bank_ref_match — Bank Statement: Match by Invoice Reference

Odoo 19 Community + OCA `account_reconcile_oca`.

**Problem.** OCA auto-matches a bank line to an invoice only when the *whole* bank
description is contained in the invoice reference. Real UK bank descriptions carry the
reference inside other text: `Jane SampleS01234`, `Alex Example SAJ/2026/0042`.

**What it does.** On import (and on demand) it extracts references from the bank
description with a configurable regular expression (Accounting → Settings → Bank & Cash),
looks each one up in the *payment reference*, *number* and *reference* of open posted
receivable/payable lines, and when exactly one line matches (same direction, same partner
if the bank line has one) it reconciles. Smaller payment → partial payment; larger payment
→ left for the user.

**Manual run.** Bank statement lines list → select → Actions → *Auto-match (rules + references)*.
Already reconciled lines are skipped; unsaved matching on the selected lines is recomputed.

Default pattern: `SAJ/\d{4}/\d{3,}|INV/\d{4}/\d{3,}|BILL/\d{4}/\d{3,}|S\d{5}`.

**Fallback: payer name + amount** (Settings → *Match bank lines by payer name and amount*,
default *Suggest*). When there is no reference, the payer is identified by the bank line
partner or by the payer name with the words in any order and without accents
(`EXAMPLE ALEX` = `Alex Example`), and if that partner has exactly one open
invoice/bill for exactly the same amount in the same currency it is:
*Suggest* — pre-filled in the reconciliation screen, the user presses Validate;
*Auto* — reconciled on import like a reference match. A single-word name is ignored.
