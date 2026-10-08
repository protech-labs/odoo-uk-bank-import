# pt_uk_setup — UK small business setup (Odoo 19 Community)

Install on a database with the UK chart (`l10n_uk`). Creates, only if missing:

- **Bank import mappings**: *HSBC UK — Business Internet Banking (CSV)*,
  *Wise — Balance statement (CSV)*, *Revolut Business — account statement (CSV)*. PayPal is imported by `pt_statement_import_paypal_csv`
  (no mapping needed).
- **Clearing account** 120090 *PayPal card holds (clearing)*.
- **Tax** *20% G (incl.)* — purchase 20 % with price included, for bank rules of
  VAT-registered clients (bank amounts are gross). Non-VAT clients: rules without tax.
- **Generic reconciliation rules**: bank/payment-provider fees → 791000; interest and
  cashback → 490000; PayPal withdrawals and the matching bank receipts → 122001
  Liquidity Transfer; PayPal card holds → 120090; wages and HMRC PAYE as *suggestions*.

Not included (client-specific): bank journals, supplier rules, opening balances.
Journal-scoped rules (PayPal/Wise) pick journals by name at install time — create the
bank journals **before** installing, or edit the rule's journals afterwards.
