# Fin wiki

This is the navigation hub for Fin's released behavior and engineering
contracts. Start with the task route below, then read only the focused pages for
the change. [The development plan](../PLAN.md) remains the authority for scope
and ordering.

## Route by task

| Task | Start here | Then verify with |
|---|---|---|
| Understand the product or propose scope | [Product and terminology](product.md) | [Decision log](decisions.md), [plan](../PLAN.md) |
| Import or change DKB parsing | [Finance algorithms](finance-algorithms.md) | [Domain model](domain-model.md), [`test_import.py`](../tests/test_import.py) |
| Change balances, summaries, trends, recurrence, transfers, or forecast | [Finance algorithms](finance-algorithms.md) | [Domain model](domain-model.md), [`test_analytics.py`](../tests/test_analytics.py) |
| Change annual reporting or print output | [Finance algorithms](finance-algorithms.md) | [Interface map](interfaces.md), [`test_web_and_localization.py`](../tests/test_web_and_localization.py) |
| Change authorization, authentication, secrets, or auditing | [Architecture and security](architecture.md) | [Domain model](domain-model.md), [`test_authorization_and_services.py`](../tests/test_authorization_and_services.py) |
| Add or change a browser route | [Interface map](interfaces.md) | [Architecture and security](architecture.md), [`test_web_and_localization.py`](../tests/test_web_and_localization.py) |
| Add or change an MCP tool | [MCP agent guide](mcp-agent-guide.md) | [Interface map](interfaces.md), [`test_mcp.py`](../tests/test_mcp.py) |
| Change localization | [Interface map](interfaces.md) | [`i18n.py`](../src/finanzplaner/i18n.py), [`test_web_and_localization.py`](../tests/test_web_and_localization.py) |
| Migrate the schema | [Development map](development.md) | [Domain model](domain-model.md), [`test_operations.py`](../tests/test_operations.py) |
| Build, release, deploy, back up, or recover | [Operator guide](operator-guide.md) | [Development map](development.md), [`test_operations.py`](../tests/test_operations.py) |

## Route by domain

- [Product and terminology](product.md) — purpose, users, settled boundaries,
  and the meaning of Fin-specific terms.
- [Architecture and security](architecture.md) — process boundaries, account
  visibility, authentication, secrets, content handling, and audit safety.
- [Domain model](domain-model.md) — durable records, relationships, database
  invariants, and migration ownership.
- [Finance algorithms](finance-algorithms.md) — DKB import, deduplication,
  balances, coverage, transfers, recurrence, summaries, trends, and forecast.
- [Interface map](interfaces.md) — browser routes, MCP tools, service flow,
  localization, and adapter constraints.
- [MCP agent guide](mcp-agent-guide.md) — token creation, capabilities, tools,
  concurrency, and safe agent behavior.
- [Development map](development.md) — setup, tests, migrations, documentation
  checks, release gates, and implementation entry points.
- [Operator guide](operator-guide.md) — Podium deployment, health, backup,
  upgrade, recovery, and troubleshooting.
- [Decision log](decisions.md) — concise choices future changes must not
  silently reverse.

## Documentation contract

Focused pages state what an area does, its invariants, its main code and test
entry points, related pages, and unsupported behavior. They link to source
instead of duplicating schemas or implementation. Run the deterministic link
check after changing any Markdown file:

```sh
uv run python scripts/check_markdown_links.py
```
