# Development map

Fin uses Python 3.13+, `uv`, FastAPI, SQLAlchemy, Alembic, pytest, Ruff, and a
small Playwright smoke suite. Runtime behavior stays offline and single-process.

## Setup and local checks

Install exactly the locked dependency graph:

```sh
uv sync --all-groups --locked
```

Run the deterministic release checks from the repository root:

```sh
uv run ruff check src tests migrations scripts
uv run python scripts/check_markdown_links.py
uv run pytest
```

The MCP and browser tests bind loopback ports. Playwright additionally needs a
local Chromium installation (`uv run playwright install chromium`). Secret
scanning, the ARM64 image smoke test, Podium acceptance, and recovery are release
or operator checks described in the [operator guide](operator-guide.md); they
are not silently substituted with source-process tests.

## Where to change code

| Change | Primary entry point | Focused tests |
|---|---|---|
| Models or schema | [`models.py`](../src/finanzplaner/models.py), [`migrations/versions/`](../migrations/versions/) | [`test_operations.py`](../tests/test_operations.py) |
| Authorization or business writes | [`services.py`](../src/finanzplaner/services.py) | [`test_authorization_and_services.py`](../tests/test_authorization_and_services.py) |
| DKB parsing/import | [`csv_import.py`](../src/finanzplaner/csv_import.py), `FinanceService.import_dkb` | [`test_import.py`](../tests/test_import.py) |
| Analytics and annual reporting | [`analytics.py`](../src/finanzplaner/analytics.py), service wrappers, [`year_report.html`](../src/finanzplaner/templates/year_report.html) | [`test_analytics.py`](../tests/test_analytics.py), [`test_web_and_localization.py`](../tests/test_web_and_localization.py) |
| Browser UI | [`web.py`](../src/finanzplaner/web.py), [`templates/`](../src/finanzplaner/templates/), [`static/`](../src/finanzplaner/static/) | [`test_web_and_localization.py`](../tests/test_web_and_localization.py), [`test_browser.py`](../tests/test_browser.py) |
| MCP | [`mcp_server.py`](../src/finanzplaner/mcp_server.py) | [`test_mcp.py`](../tests/test_mcp.py) |
| Authentication | [`security.py`](../src/finanzplaner/security.py), service/session calls | authorization and web tests |
| Backup/CLI | [`backup.py`](../src/finanzplaner/backup.py), [`cli.py`](../src/finanzplaner/cli.py) | [`test_backup.py`](../tests/test_backup.py), [`test_operations.py`](../tests/test_operations.py) |

## Change contract

Start with the acceptance condition in [PLAN.md](../PLAN.md). Reproduce a
correctness bug with a failing test, keep edits limited to that condition, and
update the governing wiki page in the same change. Every schema change gets an
explicit Alembic migration and upgrade-path coverage. Run the focused test
before the complete suite.

Markdown navigation is code-reviewed behavior. The link checker scans local
Markdown destinations and heading fragments, rejects paths outside the
repository, and exits nonzero on a broken link. Its own behavior is covered by
[`test_docs.py`](../tests/test_docs.py).

## Related and unsupported behavior

See the [wiki index](index.md), [domain model](domain-model.md), and
[operator guide](operator-guide.md). GitHub Actions are not a release gate;
deployment, publication, live data, backups, and restore drills require explicit
operator confirmation.
