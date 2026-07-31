# Changelog

## 1.2.0-rc.1 — 2026-07-31

- Added the concise documentation wiki, repository agent navigation, and a
  deterministic internal-Markdown-link check.
- Added reconciled 12-month year summaries, the authorized `get_year_summary`
  MCP tool, and localized annual HTML reports with saved monthly reviews.
- Added A4 print styling for annual reports and monthly overviews, suitable for
  browser Print-to-PDF without a PDF runtime dependency.
- Added a separate budget-adjusted balance trajectory and excluded transactions
  categorized as internal transfers or `Nicht budgetwirksam` from forecast
  history while preserving the DKB-reconciling account balance.

## 1.1.0 — 2026-07-31

This release finishes the open correctness, security, testing, and operational
work from the Fin development plan. It does not add net-new product features.

### Correctness and data integrity

- Forecast documentation and tests now consistently describe the annual
  projection through December.
- Recurring series are separated by incoming or outgoing direction, including
  migration of existing non-zero series.
- The initial Alembic revision is frozen as explicit historical schema
  operations.
- Adjacent and overlapping import batches contribute to continuous coverage.
- Category trends use real calendar-month positions and remain readable for
  archived categories.
- SQLite backup connections are closed deterministically.

### Security and verification

- Account and category discovery through MCP requires
  `transactions:read`.
- Disabling a user or resetting a password invalidates all of that user's
  browser sessions.
- All 15 MCP tools have official-client integration coverage.
- Browser authentication, administration, private imports, notes, responsive
  layouts, keyboard focus, localization, and chart fallbacks have integration
  and real-Chromium coverage.
- Locked local release checks run Ruff, the complete pytest suite, Chromium
  smoke tests, and full-history secret scanning without GitHub Actions.

### Operations

- The production image and Podium manifests use the immutable `1.1.0` tag.
- A host-only Podium acceptance stack is included.
- Manual backups run as the unprivileged application user, while Podium restores
  preserve the macOS host user's volume ownership.
- The ARM64 image passed migrations, readiness, first-run setup, import,
  restart persistence, online backup, network-disabled runtime, graceful
  SIGTERM, and an isolated restore drill.
