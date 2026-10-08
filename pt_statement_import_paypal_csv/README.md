# pt_statement_import_paypal_csv — Import PayPal Activity CSV

PayPal → Activity → Download → *Completed payments* / all activity, CSV.
Import it into a PayPal bank journal (currency = the PayPal balance currency) **without**
choosing a sheet mapping.

- one statement line per movement at **gross** (so it matches the invoice amount) and a
  separate **PayPal fee** line (match it with a reconciliation model to bank charges);
- authorisation holds (`Balance Impact = Memo`) are skipped; everything else is imported,
  including "Refused" hold cancellations, because PayPal's own balance includes them;
- rows in other currencies are skipped (one journal per currency);
- opening/closing balance from PayPal's `Balance` column; unique ID = PayPal Transaction ID.

## Changelog
- **19.0.1.0.1 (08.10.2026)** — lines keep the file's chronological order inside a day
  (payment, then its fee). Odoo sorts statement lines by date and then by *reversed*
  `sequence`; the OCA importer numbered them 1, 2, 3…, so each fee showed before its payment
  and the running balance looked wrong (closing balance was right). The parser now sets
  `sequence` itself, in reverse. Lines imported before the fix keep their old order —
  delete and re-import the statement to fix them.
