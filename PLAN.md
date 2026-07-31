# Fin development plan

Status: active  
Last updated: 2026-07-31

This is the single source of truth for future Fin development. Product and
operator documentation describe released behavior; issues and pull requests
may break down individual tasks, but they do not replace this plan.

This plan contains no net-new product features. Its behavior changes are
limited to correcting existing financial, privacy, security, and data-integrity
contracts; the remaining work is test, deployment, recovery, and release
verification.

## Product decisions

These decisions are settled unless real household usage produces evidence that
they should change.

- Fin remains a German-first, local-first household finance application for DKB
  Girokonto CSV exports.
- The architecture remains one FastAPI process, one SQLite database,
  server-rendered pages, and a shared `FinanceService` used by the web and MCP
  adapters. No microservices, queues, or external runtime dependencies.
- Imported transactions always start uncategorized. Only an authenticated human
  or an explicitly scoped external agent may assign a category.
- The application exposes MCP but never embeds, starts, or schedules an agent.
- Shared accounts are visible to active household users. Private accounts remain
  visible only to their owner; administrator status does not bypass that rule.
- The balance forecast is an **annual forecast for the remaining months through
  December**, anchored to the newest reported balance. Confirmed recurring
  entries are projected separately, their supporting transactions are removed
  from the variable baseline, and variable cash flow uses the median of up to
  the latest six complete monthly residual totals. The uncertainty band widens
  from the population standard deviation of those residuals. It is a
  deterministic estimate, not financial advice.
- Import coverage may be assembled from multiple adjacent or overlapping import
  batches. A real date gap must still make derived balances unreliable.
- Historical analytics remain readable after categories are archived.
- The next verified release will be `1.1.0`. It will be published from a private
  GitHub repository with automated lint and test checks.

## Scope boundaries

The following are not planned:

- bank APIs, scraping, or live DKB connectivity;
- automatic or rules-based categorization;
- budgets, spending limits, savings goals, or alerts;
- transaction splitting or household-member purchase attribution;
- combined net-worth, investment, loan, tax, or multi-currency features;
- a public-internet deployment profile or native mobile application.

New product features stay deferred until the current application has passed the
release gates below and has been used with real household workflows.

## Current baseline

The repository starts from version `1.0.8` and commit `465f551`.

Already implemented:

- atomic DKB CSV import with occurrence-aware deduplication;
- shared/private account authorization;
- human and agent annotations with audit history;
- deterministic transfer matching, recurrence detection, trends, and forecast;
- 15 scoped MCP tools over stateless Streamable HTTP;
- German and English server-rendered interfaces;
- verified SQLite backups and Podium deployment artifacts.

Known baseline:

- `uv run pytest` passes 36 tests;
- Ruff passes;
- the private DKB sample passes aggregate-only validation when present;
- the production container, Podium stack, responsive layout, and restore
  procedure have not yet been proven end to end;
- public documentation still contains the retired six-month forecast
  description.

## Working rules

- Each task below should be one reviewable change with its own acceptance checks.
- Reproduce correctness bugs with a failing test before changing implementation.
- Every schema change requires an Alembic migration and upgrade coverage.
- Documentation changes ship with the behavior they describe.
- Do not mix unrelated cleanup into a task.
- Deployments, remote publication, and restore drills require explicit operator
  confirmation before execution.

## Phase 1 — Establish the authoritative baseline

### F-01 — Align the annual forecast contract

Update the README, finance algorithm guide, MCP tool description, and forecast
tests to describe the settled annual-through-December method. Add horizon tests
for January, June, and December balance snapshots.

Done when every user-facing and agent-facing description matches the
implementation, and no six-month or per-category forecast claim remains.

### F-02 — Publish the private repository and add core CI

Create the private GitHub repository, add it as the remote, and run locked
dependency installation, Ruff, and pytest on every pull request. MCP tests must
be allowed to bind a loopback port. Add secret scanning before publishing the
history.

Done when a clean clone can reproduce the non-browser test suite and `main`
cannot accept a failing change.

## Phase 2 — Correctness and data integrity

### F-03 — Separate recurring series by direction

Add direction to `RecurringSeries`, its uniqueness constraint, detection lookup,
and MCP serialization. Migrate existing rows by the sign of their non-zero
typical amount. Preserve manual confirmation, rejection, disabling, and
overrides.

Done when the same counterparty can maintain independent incoming and outgoing
series with the same cadence.

### F-04 — Freeze the initial Alembic migration

Replace the live `Base.metadata.create_all()` and `drop_all()` calls in revision
`20260725_0001` with explicit historical schema operations.

Done when the initial revision no longer imports live application metadata and
fresh upgrade, downgrade, and re-upgrade tests pass through every committed
revision.

### F-05 — Merge import coverage intervals

Calculate coverage from the union of adjacent and overlapping import batches
instead of requiring one batch to cover the complete interval.

Done when two adjacent batches make a month reliable, overlapping batches remain
reliable, and a one-day gap remains visibly incomplete.

### F-06 — Correct historical category trend semantics

Use actual calendar-month positions for trend fitting, require three consecutive
calendar months for the three-month moving average, and allow archived
categories to remain readable without making them assignable.

Done when tests cover missing months, archived categories, sparse history, and
ordinary continuous history.

## Phase 3 — Complete service and security contracts

### F-07 — Exercise every MCP tool

Call all 15 tools through the official MCP client. Cover successful pagination,
invalid cursors, category conflicts, uncategorization, notes, tags, trends,
forecast, recurring series, review reads and revisions, and private-object
denial.

Settle and enforce the capability rule that account and category discovery
requires `transactions:read`; other capabilities do not implicitly grant it.

Done when every tool has a successful path and a representative capability,
account-scope, concurrency, or validation failure path.

### F-08 — Complete browser authentication and administration coverage

Add integration tests for successful and failed login, rate-limit exhaustion,
expired and disabled-user sessions, password resets, secure-cookie
configuration, user administration, category administration, human note
editing/deletion, and private-account imports.

Password resets and user disabling must invalidate existing browser sessions.

Done when every security-sensitive browser mutation has successful, CSRF
failure, and authorization failure coverage where applicable.

### F-09 — Remove test-runtime warnings

Resolve the Starlette/httpx TestClient deprecation and close SQLite resources
cleanly. Add direct tests for CLI backup and private-sample validation commands.
Do not chase an arbitrary coverage percentage.

Done when the complete non-browser suite passes without resource or deprecation
warnings.

## Phase 4 — Prove the user interface

### F-10 — Add real browser and responsive smoke tests

Add a focused Playwright suite for login, overview, transactions, forecast,
import, and transaction detail at desktop and 320–390 px mobile widths.

Check keyboard focus, tab order, navigation, horizontal overflow, long German
labels, long purposes, large euro values, empty/error states, English locale,
and chart text/table fallbacks. Keep screenshots as failure artifacts rather
than brittle pixel-perfect golden tests.

Done when the browser suite runs locally and in CI and the required pages pass
at both representative widths.

## Phase 5 — Prove operations and release `1.1.0`

### F-11 — Build and smoke-test the production ARM64 image

Build the locked `linux/arm64` image and verify migrations, readiness, first-run
setup, import, persistent data across restart, online backup, offline runtime,
and graceful SIGTERM behavior.

Done when all checks run against the built image rather than source-process test
doubles.

### F-12 — Validate Podium in an isolated stack

Run the real Podium validator, load the immutable image, and apply a host-only
test stack. Verify liveness, readiness, ingress, local DNS, resource limits,
restart behavior, and the 03:15 Europe/Berlin backup schedule.

Done when the isolated stack remains healthy through restart and produces a
verified scheduled backup.

### F-13 — Perform a recovery drill

Restore a verified backup into a separate test volume, start Fin against it, and
verify login, import history, transactions, reviews, and the latest balance.
Do not test restore against the live household database.

Done when the documented restore procedure has been executed successfully and
same-host backup limitations are recorded.

### F-14 — Reconcile documentation and cut the release

Update the operator and MCP guides with the exact verified commands and
outcomes, set version and image references to `1.1.0`, write concise release
notes, and tag the verified commit.

Done when a clean checkout can follow the documentation from build through
backup and restore, all release gates pass, and the immutable release tag is
published.

## Release gates

`1.1.0` is ready only when:

1. Ruff, pytest, MCP integration tests, and Playwright tests pass.
2. Fresh and upgraded database migrations pass.
3. The ARM64 production image passes health, persistence, backup, and shutdown
   checks.
4. The Podium stack validates and passes an isolated restart test.
5. A verified backup has completed an isolated restore drill.
6. README, algorithm, MCP, and operator documentation match released behavior.
7. The repository and release history contain no secrets or private financial
   data.
