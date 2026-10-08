# pt_statement_import_sheet_order

Fixes the opening balance of sheet (CSV/XLSX) statements exported newest
first without a time of day (Revolut Business, HSBC UK). The OCA parser sorts
by date with a stable sort, so same-day movements stayed in reversed order and
the opening balance was taken from the wrong row. If the first row is later
than the last, the rows are reversed before sorting. Oldest-first files are
untouched. Candidate for a pull request to OCA/bank-statement-import.
