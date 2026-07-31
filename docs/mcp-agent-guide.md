# MCP agent guide

Fin exposes the official MCP SDK's stateless Streamable HTTP transport
at:

```text
http://finanzen.home.arpa:8080/mcp
```

The application never starts, embeds, schedules, or contacts an agent. An
external agent initiates every interaction.

## Create a token

Sign in as the user whose account access the agent should inherit. Open
**Agent-Zugänge**, choose explicit accounts and capabilities, and create a
token. The plaintext begins with `fp_`, appears once, and is never stored by
Fin. Store it in the agent's secret manager, not in a prompt, wiki,
stack file, or source control.

Each token can be revoked and optionally expires. Disabling its user also
invalidates it. A token cannot include a private account that its issuing user
cannot access.

Send it as:

```http
Authorization: Bearer fp_REDACTED
```

This is a private-network bearer-token scheme, not a claim of full OAuth
conformance.

## Capabilities

| Capability | Permits |
|---|---|
| `transactions:read` | accounts, taxonomy, transaction facts |
| `transactions:categorize` | categorization with revision checks |
| `notes:write` | append agent-authored notes |
| `tags:write` | add tags without replacing human tag links |
| `analytics:read` | monthly/year summaries, trends, forecast, recurring series |
| `reviews:read` | read the current monthly review |
| `reviews:write` | create a new monthly-review revision |

There are no MCP tools for imports, deletes, user/category administration,
account visibility, backups, or token administration.

## Tools

The server exposes:

1. `list_accounts`
2. `list_categories`
3. `list_transactions`
4. `list_uncategorized_transactions`
5. `get_transaction`
6. `categorize_transactions`
7. `uncategorize_transactions`
8. `add_transaction_note`
9. `add_transaction_tags`
10. `get_month_summary`
11. `get_year_summary`
12. `get_category_trend`
13. `get_balance_forecast`
14. `list_recurring_series`
15. `get_monthly_review`
16. `save_monthly_review`

List calls use opaque cursor pagination. Dates are ISO 8601, monetary values
are integer euro minor units, and the currency is always explicit `EUR`.
`get_year_summary` returns all 12 calendar months and flags incomplete import
coverage. It requires `analytics:read` and omits review content and metadata;
use `get_monthly_review` with `reviews:read` for reviews.

## Safe categorization

Read transaction `revision` values immediately before mutation. Send at most
100 assignments plus a unique idempotency key. Results are per item:
`applied`, `unchanged`, or `conflict`.

An agent cannot overwrite or remove a category most recently assigned by a
human. A human can explicitly clear it, after which an agent may categorize
the new uncategorized revision. Retry the same batch with the same idempotency
key; Fin returns the stored result without duplicate audit events.

Inaccessible and nonexistent private IDs return the same stable `not_found`
error. Do not infer private-account existence from errors, counts, taxonomy,
or tag suggestions.

Monthly reviews also use optimistic concurrency: read revision 0 or the
current revision, then pass it as `expected_revision` when saving.

## Code and tests

[`mcp_server.py`](../src/finanzplaner/mcp_server.py) registers tools, validates
and serializes payloads, and authenticates bearer tokens. Every tool delegates
to [`services.py`](../src/finanzplaner/services.py).
[`test_mcp.py`](../tests/test_mcp.py) uses the official client to exercise all
tools plus token, host, capability, scope, validation, cursor, and revision
failures.

## Related and unsupported behavior

See the [interface map](interfaces.md),
[architecture and security](architecture.md), and
[finance algorithms](finance-algorithms.md). MCP does not provide import,
deletion, administration, backup, scheduling, or automatic categorization. Fin
does not start or contact an agent.
