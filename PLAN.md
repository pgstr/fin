# Fin development plan

Status: `1.1.0` complete; post-`1.1.0` roadmap active
Last updated: 2026-07-31

This is the single source of truth for future Fin development. Product and
operator documentation describe released behavior; issues and pull requests
may break down individual tasks, but they do not replace this plan.

The `1.1.0` work recorded below contained no net-new product features. It was
limited to correcting existing financial, privacy, security, and data-integrity
contracts and proving test, deployment, recovery, and release behavior. The
post-`1.1.0` section at the end of this file is the prioritized roadmap for new
product work.

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
- Actual balances always reconcile to the imported bank balance and therefore
  include every transaction. A separate budget-adjusted trajectory excludes
  transactions categorized under the transfer root, including
  `Nicht budgetwirksam`; the forecast variable baseline uses the same
  budget-neutral rule.
- Import coverage may be assembled from multiple adjacent or overlapping import
  batches. A real date gap must still make derived balances unreliable.
- Historical analytics remain readable after categories are archived.
- The verified release is `1.1.0`. It is published to a private
  GitHub repository used only as a version-control remote. Release verification
  runs locally and on the approved Podium host, not in GitHub Actions.

## `1.1.0` scope boundaries

The following were not planned for `1.1.0`:

- bank APIs, scraping, or live DKB connectivity;
- automatic or rules-based categorization;
- budgets, spending limits, savings goals, or alerts;
- transaction splitting or household-member purchase attribution;
- combined net-worth, investment, loan, tax, or multi-currency features;
- a public-internet deployment profile or native mobile application.

The post-`1.1.0` roadmap keeps most of these boundaries. It permits only the
narrow, evidence-gated exceptions stated there; an exception does not reopen
the whole surrounding product area.

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

### F-02 — Publish the private repository and define local release checks

Create the private GitHub repository and add it as the remote. Before publishing
a release, run locked dependency installation, Ruff, pytest, and secret scanning
locally. MCP and browser tests must be allowed to bind loopback ports.

Done when a clean clone can reproduce the complete local test suite and the
verified history is pushed without relying on GitHub Actions or another paid
GitHub feature.

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

Done when the browser suite runs locally and the required pages pass at both
representative widths.

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

## Completion record

All tasks F-01 through F-14 and all release gates were completed on 2026-07-31.

- Ruff passed for application code, tests, migrations, and release scripts.
- The warning-strict pytest suite passed all 55 tests, including real Chromium,
  official MCP-client, migration, CLI, and security coverage.
- Gitleaks scanned the complete repository history without finding a leak.
- The final ARM64 OCI manifest is
  `sha256:300e17152721342bc5736f833789e1a70128030969b64f2c8083cb7b94d96add`.
- The isolated `m1-pro` Podium stack passed liveness, readiness, loopback
  ingress, internal DNS, resource-limit, restart, setup, import, scheduled
  backup, and restore checks. Its disposable resources were removed afterward;
  the live stack was not changed.
- Private GitHub repository `pgstr/fin` is the version-control remote. GitHub
  Actions and other paid GitHub features are intentionally not part of the
  development or release process.

## Post-`1.1.0` product roadmap

This roadmap consolidates the current scope boundaries, the original Fin
specification, the earlier finance-spoke plans, and the current implementation.
There is no separate GitHub issue backlog. New scope must be promoted here
before implementation.

### Rating model

- **Importance** is specific to Fin: `5` is central to its household-finance
  purpose and `1` provides little value for this application.
- **Priority** is `P0` next validated slice, `P1` next product release, `P2`
  evidence-gated, `P3` distant, or `X` do not build.
- **Effort** is relative: `S`, `M`, or `L`. Every schema change still requires
  an Alembic migration and upgrade coverage.

### Previously deferred ideas that are already implemented

- local, responsive web dashboard;
- shared and private multi-account storage and navigation;
- recurring-series detection and review;
- running-balance history, trends, and annual forecast;
- agent-authored monthly reviews rendered in the web interface;
- human and external-agent categorization through one service layer.

The remaining multi-account proposal is specifically an aggregate view across
accounts already visible to one user. It is not a household-wide privacy bypass
or a net-worth product.

### Prioritized candidates

| Feature | Importance | Priority | Effort | Decision |
|---|---:|---:|---:|---|
| Concise documentation wiki and agent navigation | 5 | P0 | M | Build before and alongside new features |
| Annual and multi-year reporting | 5 | P0 | M | Build |
| Printable monthly/year HTML including saved reviews | 5 | P0 | M | Build with reporting |
| Budget-adjusted balance trajectory and forecast history | 5 | P0 | S | Build without changing the reconciled bank balance |
| Scheduled month-end review draft | 5 | P0 | S | Configure outside Fin through MCP |
| `My visible accounts` aggregate dashboard | 4 | P1 | L | Build with strict privacy semantics |
| Target balance and date | 4 | P1 | M | Build as the first narrow savings goal |
| DKB Visa or another genuinely used CSV format | 4 if used | P2 | M each | Require a real sample and workflow |
| Category budgets or targets | 3 | P2 | L | Trial only after target-balance use |
| Transaction splitting | 3 | P2 | L | Require evidence of distorted reports |
| Direct PDF generation | 2 | P3 | M | Defer while browser print is sufficient |
| Alerts or hard spending limits | 2 | P3 | L | Defer until targets and a channel exist |
| Bulk manual categorization workflow | 2 | P3 | M | Add only if agent-assisted flow is insufficient |
| Additional banks generally | 2 | P3 | M each | Add one proven format at a time |

### Settled non-goals

| Feature | Importance | Priority | Reason |
|---|---:|---:|---|
| Live bank API connectivity | 2 | X | Large credential, security, and reliability burden |
| Screen scraping | 1 | X | Fragile and unsafe to operate with bank credentials |
| Rules or catch-all automatic categorization | 2 | X | Conflicts with explicit human/agent category authority |
| Built-in ML categorization, confidence scores, or review queue | 1 | X | Duplicates the external agent and complicates provenance |
| Embedded LLM or outbound AI calls | 1 | X | MCP is the intentional agent boundary |
| Household-member purchase attribution | 1 | X | No demonstrated need for the administrative complexity |
| Full net-worth dashboard | 2 | X | Different product and data model from bank cash flow |
| Investment or securities tracking | 1 | X | Separate valuation domain and data source |
| Loan amortization | 2 | X | Recurrence already captures payment cash flow |
| Tax functionality | 1 | X | Specialized, high-stakes domain outside Fin |
| Multiple currencies | 1 | X | Current DKB/EUR workflow does not justify pervasive change |
| Native mobile application | 1 | X | Responsive local web UI covers mobile use |
| Public-internet deployment profile | 1 | X | Expands the threat model without a proven need |
| Email integration or reset email | 1 | X | Local administrator resets are sufficient |
| User-facing import rollback | 1 | X | Atomic idempotent imports make it rare and references make it risky |
| One-click restore | 1 | X | Restore is destructive and remains an operator procedure |
| Public REST API or duplicate export CLI | 1 | X | MCP already provides the structured integration surface |

### Cross-cutting track — concise documentation wiki

Fin will gain a small, hand-maintained Markdown wiki that covers the complete
system without becoming a generated code dump. Its two audiences are operators
and coding agents. The documentation is part of the product: a behavior change
is incomplete until its corresponding page is current.

The navigation contract is:

1. `README.md` gives the product overview and points to `docs/index.md`.
2. `docs/index.md` is the wiki home and routes by task and domain.
3. A short repository-local `AGENTS.md` tells agents to read this plan, the wiki
   index, and the relevant focused page before changing code.
4. Focused pages link to related pages, implementation entry points, and tests.

Initial coverage should include:

- product purpose, settled decisions, non-goals, and terminology;
- architecture and the browser/service/MCP boundaries;
- domain model and database invariants;
- account visibility, authorization, secrets, and audit rules;
- DKB import, deduplication, balances, and coverage;
- categories, annotations, transfers, recurring series, summaries, trends,
  forecast, and monthly reviews;
- web routes, MCP tools/capabilities, and localization conventions;
- development setup, migrations, testing, release checks, deployment, backup,
  and recovery;
- a concise decision log for choices that future agents must not silently
  reverse.

Every focused page should answer only:

- what the area does and why it exists;
- its invariants and privacy/security boundaries;
- the main code entry points and data flow;
- the tests that prove the contract;
- related pages and deliberately unsupported behavior.

Documentation acceptance criteria:

- every area above is reachable from `docs/index.md` in at most two links;
- the index includes task-oriented routes such as importing, changing
  analytics, adding an MCP tool, changing authorization, migrating the schema,
  and releasing;
- internal Markdown links are checked deterministically by a small local lint
  command included in release verification;
- feature changes update the relevant page and navigation in the same change;
- pages remain concise and do not duplicate source code, API schemas, or the
  operator guide verbatim;
- an unfamiliar agent can locate the governing invariant, implementation entry
  point, and relevant tests without a repository-wide search.

### Phase 0 — activate `1.1.0`, gather evidence, and build the wiki foundation

Use the released application for one complete household cycle before changing
the financial schema. If `1.1.0` is not yet live, deployment still requires
explicit operator confirmation.

Record:

- which accounts or file formats remain uncovered;
- how many transactions need manual category corrections;
- how often a transaction genuinely needs splitting;
- whether annual printable reports are used;
- whether users ask for a target balance or category budgets.

In parallel, create `docs/index.md`, the repository-local `AGENTS.md`, the
focused system-map pages, and the internal-link lint. Reconcile the existing
README, architecture, finance-algorithm, MCP, and operator documents into the
wiki navigation without duplicating their contents.

Done when one real import-to-review cycle has completed and a new agent can use
the wiki to find the code and tests for every current Fin capability.

### Phase 1 — provisional `1.2`: year reporting and review cadence

1. Add a deterministic `year_summary(account, year)` that uses the same
   financial semantics as `month_summary`.
2. Add an authorized service method and `get_year_summary` MCP tool.
3. Add a server-rendered annual report containing monthly cash flow, category
   totals, balance development, incomplete-coverage warnings, and saved reviews.
4. Add print CSS for clean A4 and browser Print-to-PDF output in German and
   English. Do not add a PDF runtime dependency yet.
5. Document the year-summary contract, report data flow, MCP addition, and
   relevant tests in the wiki.
6. Configure the end-of-month review outside Fin. It may read analytics and
   save a review through MCP; Fin must not embed or schedule the agent.
7. Keep the reconciled balance unchanged, but add a visibly separate
   budget-adjusted yearly trajectory and exclude transfer-root transactions
   from the forecast's historical variable baseline.

Done when annual totals reconcile exactly with their included month summaries,
private-account authorization is unchanged, incomplete periods remain visible,
the report prints cleanly, and the external review run remains auditable.

### Phase 2 — provisional `1.3`: `My visible accounts`

Define aggregate semantics before implementation:

- include only accounts visible to the current user;
- neutralize matched internal transfers without hiding unmatched cash flow;
- never reveal another user's private-account existence, name, balance,
  transaction, review, or contribution;
- describe the result as aggregate cash flow and cash balances, not net worth;
- preserve per-account drill-down and source reliability indicators.

Add the service aggregation before the web page or any MCP exposure. Verify
shared/private combinations, missing transfer matches, incomplete import
coverage, and direct-object access at service and adapter boundaries. Add the
aggregate semantics and privacy examples to the wiki before the UI ships.

### Phase 3 — provisional `1.4`: target balance

Add one deliberately small goal type:

- account, target date, and target balance;
- projected balance at the target date;
- projected surplus or shortfall;
- a target line on the existing forecast;
- MCP read access, but no autonomous agent mutation;
- complete model, migration, algorithm, and UI documentation in the wiki.

Do not add notifications, hard spending limits, multiple goal types, or
automated recommendations in this phase.

### Phase 4 — evidence-gated extensions

Promote at most one candidate at a time:

- a DKB Visa or other CSV importer when a real, private sample and ongoing use
  exist;
- transaction splitting when mixed purchases materially distort category
  totals;
- category targets when the target-balance feature does not answer household
  planning questions;
- direct PDF generation when browser printing is demonstrably inconvenient;
- alerts only after targets exist and a delivery channel is explicitly chosen.

Each promoted feature needs its own acceptance checks, documentation pages or
page updates, migration coverage where applicable, browser/MCP coverage where
exposed, and a separate reviewable release slice.
