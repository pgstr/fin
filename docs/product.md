# Product and terminology

Fin is a German-first, local-first household cash-flow planner for DKB
Girokonto CSV exports. It helps a small household import facts, explicitly
categorize them, understand monthly and annual cash flow, and retain auditable
reviews without sending financial data to an external runtime service.

## Invariants and boundaries

- One installation serves a trusted household, but account visibility still
  applies to every browser and agent request.
- Shared accounts are visible to active users. Private accounts are visible
  only to their owner; administrators receive no privacy bypass.
- Imports create facts, not interpretations: every new transaction begins
  uncategorized.
- Humans remain authoritative over agent category assignments. Agent access is
  explicit by account and capability.
- EUR is the only currency, DKB Girokonto CSV is the only supported input, and
  the product describes cash flow and cash balances rather than net worth.
- Analytics are deterministic estimates. The balance forecast is not financial
  advice.

The complete roadmap and rejected product areas are maintained in
[PLAN.md](../PLAN.md). The concise rationale for durable choices is in the
[decision log](decisions.md).

## Terminology

- **Account:** one imported Girokonto, marked shared or private.
- **Import batch:** aggregate metadata for one validated CSV import; the raw
  upload is never retained.
- **Reported balance:** DKB's closing balance and date recorded as a snapshot.
- **Derived balance:** a balance calculated from a snapshot and intervening
  transactions; reliability depends on import coverage.
- **Coverage:** the union of imported date intervals proving that no date is
  missing from a derived period.
- **Budget-neutral transfer:** a uniquely matched internal transfer excluded
  from cash-flow totals without changing transaction categories.
- **Recurring series:** deterministic cadence evidence grouped by counterparty
  and direction, with human review state.
- **Monthly review:** immutable, revisioned Markdown commentary authored by a
  human or scoped external agent.
- **Actor:** an authenticated human session or bearer-token agent principal.

## Code and tests

Product invariants enter through [`services.py`](../src/finanzplaner/services.py);
durable records are in [`models.py`](../src/finanzplaner/models.py); browser and
MCP adapters are in [`web.py`](../src/finanzplaner/web.py) and
[`mcp_server.py`](../src/finanzplaner/mcp_server.py). The broad contract tests
are [`test_authorization_and_services.py`](../tests/test_authorization_and_services.py),
[`test_analytics.py`](../tests/test_analytics.py),
[`test_mcp.py`](../tests/test_mcp.py), and
[`test_web_and_localization.py`](../tests/test_web_and_localization.py).

## Related and unsupported behavior

See the [architecture and security](architecture.md), [domain model](domain-model.md),
and [finance algorithms](finance-algorithms.md). Live bank connections,
scraping, embedded AI, automatic categorization, net-worth features, multiple
currencies, and a public-internet profile are deliberately unsupported.
