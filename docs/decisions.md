# Decision log

This log summarizes durable choices that future work must not silently reverse.
The current authoritative scope and priority remain in [PLAN.md](../PLAN.md).

| Decision | Reason and consequence |
|---|---|
| German-first, local-first household application | The proven workflow is DKB/EUR on a trusted home network; do not generalize without evidence. |
| One FastAPI process and one SQLite database | It is sufficient for household load and avoids competing SQLite writers and operational sprawl. |
| Shared `FinanceService` boundary | Browser and MCP must receive identical authorization and financial semantics. |
| Explicit category authority | Imports never guess categories; humans are authoritative and scoped agents have recorded provenance. |
| Owner-only private accounts | Administrator duties do not imply financial visibility; inaccessible and nonexistent objects remain indistinguishable. |
| External-agent MCP boundary | Fin exposes tools but never embeds, contacts, starts, or schedules an agent. |
| Immutable imported facts and review revisions | Corrections and commentary remain auditable; user-facing rollback and destructive restore stay out of the app. |
| Integer EUR cents and calendar dates | Current inputs are EUR cash flow; pervasive multi-currency and timezone abstractions would add unproven complexity. |
| Union-based import coverage | Adjacent or overlapping batches can prove a period; a real date gap must remain visible as incomplete. |
| Annual forecast through December | Use confirmed recurring projections plus the median of recent complete residual months and a widening population-deviation band. |
| Archived categories remain readable | Historical analytics must survive taxonomy maintenance even though archived categories cannot receive new assignments. |
| Browser print before direct PDF | Printable HTML covers the current reporting need without another runtime dependency. |
| Local release verification | Ruff, pytest, secret scanning, image checks, Podium acceptance, and restore are verified locally/on the approved host, not through paid GitHub features. |

## Implementation and tests

These decisions are enforced primarily in
[`services.py`](../src/finanzplaner/services.py),
[`analytics.py`](../src/finanzplaner/analytics.py),
[`security.py`](../src/finanzplaner/security.py), and
[`models.py`](../src/finanzplaner/models.py). Contract coverage is distributed
across [`test_authorization_and_services.py`](../tests/test_authorization_and_services.py),
[`test_analytics.py`](../tests/test_analytics.py),
[`test_mcp.py`](../tests/test_mcp.py),
[`test_web_and_localization.py`](../tests/test_web_and_localization.py), and
[`test_operations.py`](../tests/test_operations.py).

## Related and unsupported behavior

See [product and terminology](product.md),
[architecture and security](architecture.md), and
[finance algorithms](finance-algorithms.md). Proposed reversals belong in the
plan with household evidence and explicit acceptance checks before code changes.
