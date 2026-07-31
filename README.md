# Fin

Fin is a German-first, local-first household financial planner for
DKB Girokonto CSV exports. It serves the web interface, health endpoints, and
authenticated MCP tools from one FastAPI process and stores all data in
SQLite.

## What it does

- Imports DKB Girokonto CSV files atomically with occurrence-aware
  deduplication and balance snapshots.
- Keeps shared accounts visible to the household and private accounts visible
  only to their owner.
- Supports human- or agent-authored categories, notes, tags, and versioned
  monthly reviews without automatic categorization.
- Detects recurring entries, links unambiguous internal transfers, shows
  category trends, creates printable annual reports, contrasts the actual
  balance with a budget-adjusted trajectory, and forecasts account balances
  for the remaining months through December.
- Exposes 16 scoped MCP tools over stateless Streamable HTTP at `/mcp`.
- Creates verified online SQLite backups with daily and monthly retention.

## Local development

```sh
uv sync --all-groups --locked
export SESSION_SECRET=development-session-secret-change-me
export SETUP_TOKEN=development-setup-token
uv run finanzplaner serve --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`. The first-run screen requires the setup token.

Run the deterministic suite:

```sh
uv run pytest
uv run ruff check src tests migrations scripts
uv run python scripts/check_markdown_links.py
```

The MCP tests bind a temporary loopback port. Environments that sandbox
listening sockets must permit localhost for that part of the suite. The real
browser smoke test also starts a loopback server and requires Chromium:

```sh
uv run playwright install chromium
uv run pytest tests/test_browser.py
```

## Documentation

- [Wiki home](docs/index.md): task-oriented navigation across product,
  architecture, domain, interface, development, and operations contracts.
- [Development plan](PLAN.md): authoritative product decisions, ordered work,
  and release gates.
- [Changelog](CHANGELOG.md): released corrections and verification outcomes.
- [Operator guide](docs/operator-guide.md): build, deploy, initialize, back up,
  upgrade, restore, and troubleshoot.
- [MCP agent guide](docs/mcp-agent-guide.md): create a scoped token and connect
  an external agent.
- [Architecture and security](docs/architecture.md): boundaries, privacy, and
  shared service rules.
- [Finance algorithms](docs/finance-algorithms.md): deduplication, transfers,
  recurrence, trends, balance derivation, and forecasting.
