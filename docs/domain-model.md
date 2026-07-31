# Domain model

SQLAlchemy models define Fin's current durable state; Alembic revisions define
its historical schema. Business writes go through `FinanceService`, and
adapters must not mutate models directly.

## Records and relationships

| Area | Records | Governing invariant |
|---|---|---|
| Identity | `User`, `WebSession` | Usernames are unique; disabled users cannot authenticate; session tokens are stored only as digests. |
| Accounts and imports | `Account`, `ImportBatch`, `BalanceSnapshot`, `Transaction` | Shared accounts have no owner, private accounts have exactly one; one batch has one snapshot; transaction occurrence identity is unique per account. |
| Classification | `Category`, `CategoryAssignmentEvent`, `TransactionNote`, `Tag`, `TransactionTag` | Categories retain history when archived; category changes are revisioned; note and tag authorship remains explicit. |
| Analytics evidence | `TransferLink`, `RecurringSeries` | A transaction belongs to at most one transfer link; recurring identity includes account, counterparty, direction, and cadence. |
| Agent work | `MonthlyReview`, `AgentToken`, `IdempotencyRecord` | Reviews are immutable revisions; token plaintext is not stored; mutation retries are scoped to token, action, and key. |
| Audit | `AuditEvent` | Events identify actor, action, and object while excluding secrets and full financial prose. |

Amounts are signed integer euro cents. Dates are calendar dates; timestamps are
UTC-aware. Foreign keys use restrictive deletion unless a dependent record is
explicitly safe to cascade or detach. Imported bank facts are not edited.

## Data flow and privacy

[`csv_import.py`](../src/finanzplaner/csv_import.py) validates bytes into an
in-memory parsed file. `FinanceService.import_dkb` creates or selects an authorized account and commits
the batch, snapshot, transactions, transfer matches, and audit event atomically.
Reads begin with `FinanceService.visible_account_query` or `get_account`, so an
inaccessible private ID and a nonexistent ID share the same result.

Analytics in [`analytics.py`](../src/finanzplaner/analytics.py) query immutable
transaction facts plus explicit classification and recurrence state. They do
not persist derived totals or predictions.

## Schema changes and tests

[`models.py`](../src/finanzplaner/models.py) is the current model.
[`migrations/versions/`](../migrations/versions/) contains explicit upgrades and
downgrades; the initial migration is frozen and must not import live metadata.
Any model change needs a new revision plus fresh upgrade, downgrade, and
re-upgrade coverage in [`test_operations.py`](../tests/test_operations.py).

Model and authorization behavior is also exercised in
[`test_authorization_and_services.py`](../tests/test_authorization_and_services.py),
import invariants in [`test_import.py`](../tests/test_import.py), and derived
semantics in [`test_analytics.py`](../tests/test_analytics.py).

## Related and unsupported behavior

See [architecture and security](architecture.md),
[finance algorithms](finance-algorithms.md), and
[development](development.md). There is no event-sourced transaction store,
multi-currency ledger, deletion workflow for imported facts, or schema creation
from live application metadata.
