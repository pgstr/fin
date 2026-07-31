# Fin repository guidance

Before changing Fin, read [PLAN.md](PLAN.md), [docs/index.md](docs/index.md),
and the focused page linked from the wiki for the area being changed. The plan
is the scope authority; the wiki records current released behavior and code
entry points.

## Product constraints

- Keep Fin German-first, local-first, single-process, SQLite-backed, and
  server-rendered.
- Route browser and MCP behavior through `FinanceService`; do not duplicate
  account authorization in an adapter.
- Preserve private-account non-disclosure. Administrator status does not grant
  access to another user's private account.
- Imported transactions begin uncategorized. Only authenticated humans and
  explicitly scoped agents may categorize them.
- Store euro amounts as integer cents and use Alembic for every schema change.
- Do not add embedded agents, automatic categorization, runtime internet
  dependencies, or other items rejected in the plan.

## Change workflow

1. State the governing invariant and acceptance check.
2. Add a failing test before fixing a correctness bug.
3. Make the smallest change that satisfies the roadmap item.
4. Update the relevant wiki page and navigation with behavior changes.
5. Run the focused test, then the documented local checks in
   [docs/development.md](docs/development.md).

Deployment, publication, backup restoration, and real household-data work
require explicit operator confirmation.
