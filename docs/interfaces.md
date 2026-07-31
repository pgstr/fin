# Interface map

Fin has two adapters over one service layer: server-rendered browser pages for
humans and stateless Streamable HTTP MCP tools for external agents. Both use the
same `FinanceService` authorization and financial behavior.

```text
browser form + session + CSRF ─┐
                              ├─ FinanceService ─ SQLAlchemy ─ SQLite
MCP tool + bearer principal ───┘
```

## Browser

[`web.py`](../src/finanzplaner/web.py) creates the FastAPI application,
authenticates the session, applies CSRF to mutations, chooses the visible
account, and prepares template context.
[`templates/`](../src/finanzplaner/templates/) renders HTML;
[`static/`](../src/finanzplaner/static/) contains bundled CSS and framework-free
JavaScript.

Routes cover setup and login, overview, transactions and detail, import,
categories, annual report, trends, forecast, recurring review, monthly review,
agent tokens, users, locale settings, and health. The annual report renders all
12 month summaries, category totals, coverage warnings, balances, and saved
reviews. Overview balance graphs contain only the bank-reconciling actual
balance and the annual forecast; budget-neutral transactions affect summary
and forecast calculations without creating another plotted balance series.
Shared print CSS produces A4 monthly or annual output through the browser
without a PDF dependency. Financial calculations and scoped reads remain
service calls rather than route-local queries.

Tests: [`test_web_and_localization.py`](../tests/test_web_and_localization.py)
covers route, session, CSRF, authorization, and translated behavior.
[`test_browser.py`](../tests/test_browser.py) covers the real Chromium flow,
keyboard use, mobile widths, overflow, and visual fallbacks.

## MCP

[`mcp_server.py`](../src/finanzplaner/mcp_server.py) owns bearer middleware,
request validation, serialization, stable error envelopes, and the registered
tools. A context-bound agent actor is passed into `FinanceService`; the adapter
never expands the token's account list or capabilities.

The complete tool and capability contract is in the
[MCP agent guide](mcp-agent-guide.md). `tests/test_mcp.py` calls the transport
through the official MCP client and covers every tool plus representative
scope, validation, concurrency, and capability failures in
[`test_mcp.py`](../tests/test_mcp.py).

## Localization

[`i18n.py`](../src/finanzplaner/i18n.py) is the German and English catalog plus
money/date formatting. German is the default. Templates and server errors use
translation keys; MCP payload field names remain stable English identifiers
while localized labels follow the token owner's locale. Both catalogs must
contain identical keys, proved by
[`test_web_and_localization.py`](../tests/test_web_and_localization.py).

## Related and unsupported behavior

See [architecture and security](architecture.md), [domain model](domain-model.md),
and [development](development.md). Fin has no public REST API, client-side
application framework, CDN assets, duplicate business logic in adapters, MCP
import/admin/delete tools, or embedded agent scheduler.
