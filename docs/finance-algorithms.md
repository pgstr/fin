# Finance algorithms

These algorithms are deterministic and never assign semantic categories.

## DKB import and deduplication

The parser uses Python's CSV module with UTF-8 BOM handling, semicolon
delimiters, quoting, German dates, decimal commas, non-breaking spaces, and
the exact 12-column Girokonto header. Metadata dates accept two- and four-digit
years, including export periods that span multiple years.

For each row, Fin canonicalizes all 12 original fields without
collapsing meaningful internal text, then hashes the account ID and canonical
fields. Repeated equal signatures receive occurrence indexes 0, 1, and so on
within that file. The database uniqueness constraint is:

```text
(account_id, signature, occurrence_index)
```

That preserves two genuinely equal bookings in one export while making exact
reimports and overlapping periods idempotent. File SHA-256 is a fast path,
not the identity rule.

## Balance derivation and coverage

Every import records DKB's reported closing balance and date. To calculate a
balance on another date, Fin starts from the newest snapshot and
adds or subtracts signed transactions between the two dates.

A derived balance is marked reliable only when the union of adjacent or
overlapping import periods covers the complete intervening period. A real
date gap remains incomplete. Otherwise the UI labels the balance potentially
incomplete instead of displaying false precision.

The actual balance and every balance graph include every transaction so that
they continue to reconcile to DKB. There is no separate adjusted-balance line.
Budget-neutral treatment is limited to cash-flow summaries and forecast
history.

## Internal transfers

An outgoing and incoming side link only when:

- signed amounts are exact opposites;
- booking dates are within three days;
- the outgoing counterparty IBAN identifies the incoming account and the
  reverse side is blank or supports the outgoing account; and
- the match is unique in both directions.

Ambiguity produces no link. Linking never changes a category.

## Recurring series

Transactions are grouped by normalized display counterparty and direction.
At least three amount-compatible entries are needed. Compatible means within
5% of the median amount, with a minimum one-euro tolerance.

Most adjacent intervals must fit one documented window:

- weekly: 6–8 days;
- monthly: 25–35 days;
- quarterly: 80–100 days;
- yearly: 350–380 days.

The UI shows transaction dates, intervals, and amount range as evidence.
Human confirmation, rejection, cadence corrections, amount/date overrides,
and disabling set a manual flag that later detection runs do not overwrite.

## Category trends

Only complete calendar months are fitted, up to the latest 12. A
three-calendar-month arithmetic moving average appears only for three
consecutive calendar months. With at least three points, the linear trend is
ordinary least squares against each observation's real calendar-month
position, so a missing month is not compressed away. There is no polynomial
fit.

## Monthly and annual summaries

`month_summary` calculates one calendar month's incoming, outgoing, net cash
flow, balances, root-category expense breakdown, categorization state, import
coverage, and latest saved review. Transactions categorized under the transfer
root remain visible but are budget-neutral in incoming, outgoing, net, and
expense totals.

`year_summary` contains all 12 calendar-month summaries, including months with
incomplete coverage. Every annual flow, count, and category total is the exact
sum of the corresponding included monthly values; root-category and transfer
semantics are unchanged. Opening and closing balances retain their individual
reliability flags, and incomplete months are listed explicitly rather than
discarded. The browser report may render saved reviews. The MCP analytics tool
omits review content because review access is a separate capability.

## Annual balance forecast

The forecast starts from the newest reported balance and excludes the current
partial month from history. It projects the remaining months of the snapshot
year through December.

Confirmed recurring entries are projected individually on their expected
dates. Historical transaction IDs supporting those series are removed from
the variable baseline to prevent double counting. Transactions categorized
under the transfer root are also removed from that baseline, matching monthly,
and annual cash-flow semantics.

Remaining cash flow uses the median of up to the latest six complete monthly
residual totals. This deliberately favors a stable household-level estimate
over a more sensitive category-by-category extrapolation.

Monthly projected flows accumulate into the balance. Population standard
deviation of historical total residuals is multiplied by the square root of
the horizon to form a widening symmetric uncertainty band. This is a simple
statistical estimate, not financial advice.

## Code and tests

Parsing and occurrence signatures live in
[`csv_import.py`](../src/finanzplaner/csv_import.py); atomic persistence,
transfer matching, and recurring detection enter through
[`services.py`](../src/finanzplaner/services.py); summaries, balance derivation,
coverage, monthly/year summaries, trends, and forecasts live in
[`analytics.py`](../src/finanzplaner/analytics.py).

[`test_import.py`](../tests/test_import.py) proves parser, deduplication,
mismatch, raw-file, and private-sample behavior.
[`test_analytics.py`](../tests/test_analytics.py) proves coverage gaps,
transfers, reconciled balance graphs, budget-neutral forecast history,
monthly/year summaries, archived history, calendar spacing, recurrence, and
forecast horizons. Adapter presentation is covered in
[`test_mcp.py`](../tests/test_mcp.py) and
[`test_web_and_localization.py`](../tests/test_web_and_localization.py).

## Related and unsupported behavior

See the [domain model](domain-model.md), [architecture and security](architecture.md),
and [interface map](interfaces.md). Algorithms do not assign categories, hide
incomplete coverage, connect to a bank, model currencies other than EUR, or
provide investment, loan, tax, or net-worth calculations.
