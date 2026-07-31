# One-go implementation prompt: Fin

Copy the complete prompt below into a new Codex task.

---

/goal Build a complete, production-ready, local-first household financial planner web application named **Fin** in this repository. Implement and verify the whole application, including its agent-facing MCP server and its Podium deployment artifacts. Do not merely produce a plan or prototype.

## Working method

- Read and follow the repository's `AGENTS.md` before making changes.
- Work autonomously through implementation, tests, container packaging, and documentation. Ask only if a genuinely blocking decision cannot be inferred from this specification.
- Keep the architecture simple and monolithic. Do not add speculative features.
- Treat `/Users/streller/knowledge-base/spokes/podium/` as read-only reference material. In particular, consult its `AGENTS.md`, `README.md`, `docs/operator-guide.md`, `docs/compatibility.md`, and examples before creating the deployment files. Do not modify Podium.
- Treat `/Users/streller/Downloads/sample-transactions-35.csv` as private, read-only reference input. Use it for local validation if it exists, but do not copy it into the repository, commit its contents, log its contents, or reproduce personal/account data in documentation or test output. Create synthetic DKB fixtures for the committed test suite.
- Preserve unrelated existing files and changes.

## Product objective

Create a German-first web application for importing DKB Girokonto CSV exports, viewing household finances month by month, categorizing transactions manually or through an external agent, reviewing category trends, identifying recurring transactions, and projecting the account balance six months into the future.

The application itself must never choose transaction categories. Every imported transaction starts uncategorized. Categories may be assigned only by an authenticated human in the web UI or by an explicitly authorized external agent calling an MCP tool.

The external agent initiates all agent work. The application exposes MCP but does not run, call, embed, or schedule an agent. There is no per-account categorization mode, rule engine, confidence threshold, or automatic review queue.

The primary use case is a shared household Girokonto. Optional private Girokonten belong to individual users and must not be visible to other users.

## Explicit non-goals

Do not implement:

- Bank APIs, screen scraping, or live DKB connectivity
- Separate Visa account imports
- An embedded LLM or outbound calls to an AI provider
- Automatic, rules-based, heuristic, or ML category assignment
- Budgets, spending limits, savings goals, or alerts
- Transaction splitting
- Purchase attribution to individual household members
- A combined net-worth or all-account dashboard
- Investment, securities, loan-amortization, or tax functionality
- Multiple currencies; this version is EUR-only
- A native mobile application
- Public-internet deployment assumptions

Recurring-series detection, deterministic transfer matching, and numerical forecasting are allowed because they do not assign semantic spending categories.

## Prescribed technical architecture

Implement a single Python application:

- A currently supported Python 3 release with an ARM64-compatible official slim Linux base image; prefer Python 3.13 unless a dependency requires another supported version
- FastAPI/Starlette
- Server-rendered Jinja templates
- HTMX or small, framework-free JavaScript enhancements where they materially help
- Locally bundled charting assets, such as Chart.js; no runtime CDN dependencies
- SQLAlchemy 2 and Alembic
- SQLite with foreign keys enabled, WAL mode, busy timeout, and integer euro cents rather than binary floating-point monetary values
- The official Model Context Protocol Python SDK, exposing stateless Streamable HTTP at `/mcp`
- `uv` with a committed lockfile for Python dependencies
- `pytest` for unit and integration tests, plus a small set of browser-level workflow tests

Serve the website, health endpoints, and MCP endpoint from the same application process. Business rules and authorization must live in application services shared by the UI and MCP adapters. Neither adapter may bypass the service layer or access the database ad hoc.

Run one web process rather than multiple database-writing workers. This application has very low concurrency: two household users and a small number of agent calls. Do not introduce PostgreSQL, Redis, Celery, a message broker, or microservices.

Bundle all necessary frontend assets into the image so the application remains usable without internet access.

## Localization

- German is the complete default language.
- English is an optional per-user language.
- Every user-visible application string, validation message, navigation label, date, number, currency value, empty state, and error must use the localization system.
- German formatting uses `de-DE`, EUR, decimal commas, and the `Europe/Berlin` time zone.
- English uses corresponding English translations and locale formatting.
- MCP tool names and stable machine-readable error codes may be English for interoperability. Returned category labels use the requesting user's or token's configured language, with German as the fallback.
- Built-in categories have stable machine keys and German and English labels. User-created labels are stored exactly as entered and are not machine-translated.
- Add automated checks that catch missing translation keys.

## Users, accounts, and privacy

This is a single-household installation, not a multi-tenant SaaS product.

### Users

- Local username-and-password authentication
- Passwords hashed with Argon2id using a maintained library
- Secure server-side sessions or securely signed opaque sessions
- HTTP-only and SameSite cookies; make the `Secure` flag configurable for HTTP-only home-network deployments versus HTTPS ingress
- CSRF protection on browser mutations
- Login rate limiting appropriate for a small local service
- No email integration or password-reset email
- On an empty database, a first-run setup page creates the first administrator and requires a one-time `SETUP_TOKEN` supplied through a Podium secret
- Ignore the setup token and disable the setup route after the first administrator exists.
- Administrators can create/disable users and reset local passwords

An administrator can manage the installation, but ordinary application queries must not grant administrators implicit read access to another user's private financial data. Document clearly that the host/server operator can still access database files and backups and therefore application privacy is not cryptographic privacy from the server owner.

### Accounts

Each account has:

- Stable ID
- Display name
- Normalized IBAN
- Type, initially only `Girokonto`
- Visibility: `shared` or `private`
- Owner for private accounts
- Creation and audit metadata

Rules:

- All active users can view and import into shared accounts.
- Only the owner can view and import into a private account.
- Private account existence, name, IBAN, balances, transactions, import history, reviews, and analytics must not leak through pages, search, counts, errors, direct object IDs, or MCP calls.
- The shared Girokonto is the default account after login.
- Do not create a combined dashboard. Users navigate accounts independently.
- Test horizontal authorization at the service and HTTP/MCP boundaries.

## DKB Girokonto CSV import

Support the supplied DKB Girokonto export shape. It contains:

1. Account type and account IBAN metadata
2. Export period metadata
3. Reported closing balance and balance date
4. A blank separator row
5. A 12-column transaction header
6. Transaction rows

The parser must correctly handle:

- UTF-8 with BOM
- Semicolon delimiters and CSV quoting
- German `dd.mm.yy` dates, while accepting four-digit years defensively
- German decimal commas
- Non-breaking spaces and the euro symbol in balance metadata
- Empty optional fields
- Very long purposes/descriptions
- Zero-value booked entries
- The exact columns:
  - `Buchungsdatum`
  - `Wertstellung`
  - `Status`
  - `Zahlungspflichtige*r`
  - `Zahlungsempfänger*in`
  - `Verwendungszweck`
  - `Umsatztyp`
  - `IBAN`
  - `Betrag (€)`
  - `Gläubiger-ID`
  - `Mandatsreferenz`
  - `Kundenreferenz`

Use a real CSV parser; do not split lines manually. Normalize structural fields for querying while preserving the original fields as a JSON audit payload on each transaction.

### Import workflow and invariants

- The account is identified by the account IBAN in the file, never merely by a user-selected target.
- If the IBAN is unknown, let the user create the account and choose `shared` or `private` before committing the import.
- If an existing account's IBAN does not match, reject the import.
- Validate the complete file before writing transactions.
- Reject unknown layouts or unsupported statuses rather than guessing.
- Initially support booked (`Gebucht`) rows. Report a clear German error if the file contains an unsupported transaction status.
- Commit each file atomically.
- Store an import-batch record containing account, uploader, file SHA-256, import time, export period, reported balance/date, row count, inserted count, and duplicate count.
- Do not retain the uploaded raw file.
- Create a balance-snapshot record from the DKB balance metadata.
- Imported bank fields are immutable in the normal application and MCP interfaces.
- Every newly inserted transaction has no category and no tags or notes.
- The importer must not invoke categorization logic.
- After success, show a German result such as “342 Buchungen verarbeitet: 317 neu, 25 bereits vorhanden.”
- Keep import-batch provenance for diagnostics, but do not implement a user-facing rollback feature.

### Deduplication

Imports must be idempotent across:

- Uploading the exact same file twice
- Overlapping export periods
- Multiple genuinely identical transactions on the same day

Implement occurrence-aware deduplication:

1. Canonicalize all 12 original transaction fields without discarding meaningful distinctions.
2. Hash the account ID plus those canonical fields into a transaction signature.
3. Within each import, assign an occurrence index among rows sharing the same signature.
4. Enforce uniqueness on account, signature, and occurrence index.
5. Use the file hash as a fast path, not as the only deduplication mechanism.

Two identical legitimate rows in one export must create two transactions; importing that export again must create zero.

If the private sample file exists, validate locally that it yields 342 transaction rows, a reported balance of EUR 572.26, 325 outgoing rows, 17 incoming rows, and one zero-value row. Do not expose its account data in output.

## Transaction model and annotations

Store at least:

- Stable opaque ID
- Account
- Booking and value dates
- Status and DKB direction
- Signed amount in integer cents and currency `EUR`
- Payer, payee, purpose, counterparty IBAN, creditor ID, mandate reference, customer reference
- A deterministically derived display counterparty that does not replace the original fields
- Import batch and raw-field audit payload
- Deduplication signature and occurrence index
- Nullable category
- Category assignment provenance and revision
- Transfer link where applicable
- Creation metadata

### Category authority

- A human category assignment is authoritative.
- An MCP agent must not overwrite or remove a category most recently assigned by a human.
- A human can change any assignment or explicitly return a transaction to uncategorized, after which an agent may categorize it again.
- Agent and human changes are recorded in an immutable audit trail.
- There is no “automatic category” status or confidence score.

### Notes

Notes are authored entries, not a single last-writer-wins field:

- Each note records its human user or agent-token author, timestamps, and plain text or sanitized Markdown.
- Agents may add notes but cannot edit or delete human notes.
- Humans can manage their own notes.
- Rendering must disallow unsafe HTML and scripts.

### Tags

- Transactions may have zero or more free-form tags.
- Tags are annotations, not categories.
- The agent may add tags through MCP without replacing human-added tags.
- Tag suggestions and lists must not leak data from inaccessible private accounts.

Do not implement transaction splitting.

## Categories

Use a shared installation-wide taxonomy with at most two levels. Root categories are organizational; leaf categories are assignable. Categories have stable IDs and machine keys, ordering, German and English labels where built in, active/archived status, and audit metadata.

- Administrators manage categories.
- Allow creation, renaming, reordering, and archiving.
- A category used by transactions cannot be hard-deleted.
- Archiving does not alter historical transactions.
- `null` represents uncategorized; do not create a fake “Nicht kategorisiert” category.
- Agents may read the taxonomy but may not create, rename, archive, or reorder categories.

Seed the following editable taxonomy:

| Key | German | English | Leaves |
|---|---|---|---|
| `income` | Einnahmen | Income | Haushaltsbeitrag / Household contribution; Gehalt & Lohn / Salary & wages; Erstattung & Rückzahlung / Refund; Zinsen & Kapitalerträge / Interest & investment income; Verkauf / Sale; Sonstige Einnahmen / Other income |
| `housing` | Wohnen & Haushalt | Housing & household | Miete & Immobilienkredit / Rent & mortgage; Energie / Energy; Wasser & Abwasser / Water & sewage; Internet & Festnetz / Internet & landline; Rundfunkbeitrag / Broadcasting fee; Haushaltswaren / Household goods; Einrichtung & Möbel / Furniture; Reparatur & Instandhaltung / Repairs & maintenance |
| `groceries` | Lebensmittel & Drogerie | Groceries & drugstore | Supermarkt & Lebensmittel / Groceries; Bäckerei / Bakery; Drogerie / Drugstore |
| `dining` | Gastronomie | Dining | Restaurant / Restaurant; Café / Café; Lieferdienst & Imbiss / Delivery & takeaway |
| `mobility` | Mobilität | Mobility | Tanken / Fuel; Laden / EV charging; Öffentlicher Nahverkehr / Public transport; Fahrzeugkosten / Vehicle costs; Parken & Maut / Parking & tolls; Taxi & Mietwagen / Taxi & rental car |
| `insurance` | Versicherungen | Insurance | Haftpflicht / Liability; Hausrat / Home contents; Kfz-Versicherung / Vehicle insurance; Kranken- & Zusatzversicherung / Health insurance; Lebensversicherung / Life insurance; Sonstige Versicherung / Other insurance |
| `health` | Gesundheit | Health | Arzt & Behandlung / Doctor & treatment; Apotheke / Pharmacy; Therapie / Therapy; Medizinische Hilfsmittel / Medical aids |
| `communication` | Kommunikation & Abos | Communication & subscriptions | Mobilfunk / Mobile phone; Software & Cloud / Software & cloud; Streaming & Medien / Streaming & media; Mitgliedschaften / Memberships |
| `leisure` | Freizeit & Kultur | Leisure & culture | Hobby / Hobbies; Sport / Sports; Veranstaltungen / Events; Bücher & Medien / Books & media |
| `shopping` | Einkäufe | Shopping | Kleidung & Schuhe / Clothing & shoes; Elektronik / Electronics; Allgemeiner Einkauf / General shopping |
| `family` | Familie & Bildung | Family & education | Betreuung / Childcare; Schule & Bildung / School & education; Kinderbedarf / Children’s needs |
| `travel` | Reisen | Travel | Unterkunft / Accommodation; An- & Abreise / Travel transport; Aktivitäten / Activities |
| `finance` | Finanzen & Behörden | Finance & government | Bankgebühren / Bank fees; Steuern & Abgaben / Taxes & levies; Kreditzinsen / Loan interest; Verwaltung & Behörden / Administration & government |
| `gifts` | Geschenke & Spenden | Gifts & donations | Geschenke / Gifts; Spenden / Donations |
| `cash` | Bargeld | Cash | Bargeldabhebung / Cash withdrawal; Bareinzahlung / Cash deposit |
| `transfers` | Transfers | Transfers | Interner Transfer / Internal transfer |
| `other` | Sonstiges | Other | Kontoinformation / Account information; Sonstiges / Other |

Use stable leaf keys derived from the English labels. Seed data must be migration-safe and idempotent.

## Transfers and household contributions

Household members generally transfer money from optional private accounts into the shared account.

- On the shared account, such incoming transactions can be categorized manually or by the agent as `Einnahmen → Haushaltsbeitrag`.
- This is household funding in the shared-account month view.
- Importing private accounts is optional and must not affect the usefulness of the shared account.
- When both sides exist, deterministically link an outgoing and incoming transaction as an internal transfer only when:
  - amounts are exact opposites,
  - dates are within a small documented window,
  - account/counterparty IBAN information supports the match, and
  - the match is unique.
- If multiple candidates exist, do not guess.
- Transfer linking does not assign or change a category.
- A user viewing only the shared side must not learn the private account name, balance, transactions, owner-only metadata, or private-side notes.

There is no combined dashboard in this release, but keep transfer links structurally correct for future aggregate reporting.

## Web interface

Design a calm, content-first household banking interface. German is the default. The result must feel like a trustworthy personal finance product, not a generic administration dashboard.

Use the approved visual direction below:

- Restrained, neutral visual styling with excellent contrast and generous but efficient spacing
- Clear typographic hierarchy and tabular monetary figures
- Minimal decorative color; reserve chart colors for persistent data meaning
- No gradients, gamification, celebratory effects, decorative illustrations, glass effects, nested cards, or walls of dashboard tiles
- Never use red/green alone to communicate income, expense, success, or failure; always pair meaning with signs, labels, and accessible text
- At most three summary cards at the top of the account overview
- One dominant balance chart rather than a collection of competing miniature charts
- Quiet tables with horizontal separation, readable merchant/purpose hierarchy, right-aligned amounts, and restrained category badges
- Clearly distinguish calculated financial data from agent-authored commentary
- Progressive disclosure: show the most useful monthly information first and put raw imported details, audit history, and advanced controls on detail pages
- Labeled controls and familiar icons; do not create icon-only navigation that requires guessing

If it remains available, use the approved interactive concept at `/Users/streller/.codex/visualizations/2026/07/25/019f9a2f-6f3e-7682-a23e-e2145ea7cd79/finanzplaner-ui-concept.html` as a visual reference. The implementation must not depend on that file.

### Navigation and responsive behavior

- Desktop uses a compact top bar with product name, visible-account selector, and user/settings access.
- Desktop primary navigation is horizontal: `Übersicht`, `Buchungen`, `Prognose`, `Kategorien`, and `Import`.
- Do not use a permanent desktop sidebar.
- Mobile prioritizes `Übersicht`, `Buchungen`, and `Prognose` in a compact bottom navigation. Put category administration, import, and settings in an accessible secondary menu.
- Preserve the selected account and month while moving among overview, transactions, and forecast where that behavior is unsurprising.
- Support widths from 320 px upward without page-level horizontal scrolling, clipped values, overlapping controls, or unusable tables.
- On narrow screens, summary cards and dashboard columns stack in reading order; the most decision-relevant content appears first.

### Account overview composition

The account overview should follow this hierarchy:

1. Account context and calendar month, with previous/next controls and a month picker
2. Three compact summary cards:
   - closing/current account balance and its effective date,
   - incoming amount with household-contribution context,
   - outgoing amount with uncategorized-transaction count
3. A large account-balance chart:
   - actual history uses a solid line,
   - forecast uses a dashed line,
   - the uncertainty range uses a subtle band,
   - labels clearly mark where observed data ends and estimated data begins
4. A restrained horizontal breakdown of the largest expense categories
5. A short recent-transactions table with a link to the complete transaction view
6. The saved agent-authored monthly review, visually presented as editorial commentary after the calculated financial data

The forecast page expands the balance projection and shows the recurring entries included in the calculation. The transaction page prioritizes search, month, category, and uncategorized filters above a readable table. Keep manual categorization available as a simple category selector without building extensive keyboard or bulk-edit workflows, because categorization will normally be performed by an agent.

Required pages:

- First-run setup
- Login/logout
- Shared-account current-month dashboard
- Account selector showing only visible accounts
- Month navigation with previous/next buttons and month picker
- Transaction list with filters for month, category, uncategorized, direction, tag, amount, and text
- Transaction detail showing immutable imported facts, category, tags, notes, audit information, and any transfer link with privacy-safe presentation
- Minimal manual category selector
- DKB import page and import history
- Category administration
- Recurring-series review
- Six-month forecast
- Saved monthly agent review
- User administration
- Agent-token administration
- Language and user settings

The default overview for an account/month shows:

- Opening and closing balance when derivable
- Total incoming, total outgoing, and net cash flow
- Household contributions
- Categorized and uncategorized totals
- Expense distribution by category
- Comparison with the previous month
- Comparison with the same month in the previous year when available
- Uncategorized count
- Transactions
- The saved Markdown monthly review, if one exists

All numerical views are computed from current data. A monthly review is a separate authored artifact and is not required for the dashboard to exist.

Calculate historical balances from the newest suitable DKB balance snapshot and signed transactions. Detect incomplete import coverage and label unavailable or potentially incomplete balances rather than presenting false precision.

### Visual quality and accessibility verification

- Use semantic landmarks, headings, tables, labels, and native controls.
- Maintain visible keyboard focus and logical tab order.
- Charts require accessible names/descriptions and a textual or tabular fallback for their important values.
- Respect reduced-motion preferences; no information may depend on animation.
- Use German realistic synthetic fixtures in UI and screenshot tests, never the private DKB sample.
- Add browser-level visual smoke checks at representative desktop and narrow-mobile widths for the overview, transactions, forecast, import, and login pages.
- Verify that long German labels, long transaction purposes, large euro values, empty states, validation errors, and the optional English locale do not break the layout.

## Monthly reviews

- One logical current review per account and calendar month
- Markdown content
- Human user or agent author
- Immutable revision history
- Safe Markdown rendering with raw HTML disabled or sanitized
- Users with account access can read the review.
- Human users can create a new revision.
- Authorized agents can read and save a new revision through MCP.
- Private-account review existence and content must not leak.

## Recurring-series detection

Implement deterministic recurring-series detection without assigning categories.

- Identify candidates from repeated normalized counterparties/references, compatible signed amounts, and approximately weekly, monthly, quarterly, or yearly intervals.
- Avoid matching transfers across unrelated counterparties.
- Show the evidence used for a candidate.
- Users can confirm a series, reject it, correct its cadence, and override the expected next date or typical amount.
- Persist manual decisions.
- Manual confirmation/rejection/overrides take priority over later detection runs.
- A confirmed series can be disabled without deleting its history.
- Keep the algorithm documented and covered by deterministic fixtures; do not introduce an ML dependency for it.

## Trends and six-month forecast

The application computes forecasts; the external agent only reads and comments on them.

### Category trends

- Aggregate leaf-category income and spending by complete calendar month.
- Show up to 12 months of history.
- Show the three-month moving average where possible.
- Fit a simple linear trend over up to the latest 12 complete months when at least three complete months exist.
- Use no polynomial fit.
- Label sparse or incomplete data clearly.

### Balance forecast

- Forecast six calendar months from the newest trustworthy reported balance.
- Exclude the current partial month from historical fitting.
- Add individually projected confirmed recurring entries on their expected dates.
- Avoid double-counting those recurring entries in the remaining variable cash-flow baseline.
- For non-recurring residual cash flow, use per-category monthly history:
  - with at least three complete months, use a documented simple linear least-squares trend over at most 12 months;
  - with fewer observations, use a flat arithmetic mean;
  - never project expense or income across zero into the opposite direction merely because of the fitted slope.
- Sum projected signed flows into a projected balance.
- Derive and display a simple uncertainty band from historical residual variation that widens with the horizon.
- Mark the result prominently as a statistical estimate rather than financial advice.
- If there is insufficient history or no trustworthy balance snapshot, explain what is missing instead of inventing a projection.
- Keep all calculations deterministic, testable, and documented.

## MCP server

Creating the MCP server is a mandatory part of the implementation and definition of done, not a future extension.

### Transport and authentication

- Mount the official Python MCP SDK's stateless Streamable HTTP application at `/mcp`.
- Use bearer service tokens suitable for this private home-network deployment. Do not claim full OAuth conformance.
- Generate high-entropy tokens, show plaintext only once, and store only a secure hash plus a non-secret identifying prefix.
- Tokens are revocable and have an optional expiry.
- Each token belongs to a user/agent identity and is scoped to explicit account IDs and capabilities.
- A token can never grant access to an account its issuing user could not access.
- Enforce authorization inside shared application services, not only at HTTP middleware.
- Never log bearer tokens or full financial payloads.

Capabilities should include:

- `transactions:read`
- `transactions:categorize`
- `notes:write`
- `tags:write`
- `analytics:read`
- `reviews:read`
- `reviews:write`

Category read access is implied by transaction read access. Do not provide MCP capabilities for importing files, deleting transactions, managing categories, managing users, changing account visibility, managing other tokens, or restoring backups.

### Required MCP tools

Implement at least these tools with typed schemas and concise descriptions:

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
11. `get_category_trend`
12. `get_balance_forecast`
13. `list_recurring_series`
14. `get_monthly_review`
15. `save_monthly_review`

Requirements:

- Use opaque cursor pagination with a default and maximum page size.
- Use ISO dates, integer minor currency units, and explicit `EUR`.
- Return stable machine-readable error codes.
- Never reveal whether an inaccessible private object exists.
- Include transaction revision numbers.
- `categorize_transactions` accepts up to 100 assignments containing transaction ID, category ID, and expected transaction revision. It returns per-item applied, unchanged, or conflict results and supports an idempotency key.
- Agent categorization must conflict rather than overwrite a human-authored assignment.
- `uncategorize_transactions` may remove an agent-authored category but must conflict on a human-authored assignment.
- `add_transaction_note` appends an agent-authored note; it never replaces another note.
- `add_transaction_tags` adds tags and does not remove human tags.
- `save_monthly_review` creates a new revision and supports optimistic concurrency.
- Every MCP mutation writes a sanitized audit event containing actor, action, affected IDs, and time but not the complete private payload.

The normal browser API may remain internal. Do not create a second public REST integration surface merely to duplicate MCP.

## Auditability

Maintain an append-only application audit log for:

- Imports
- Category changes
- Notes and tags
- Category administration
- Account and user administration
- Agent-token lifecycle
- MCP mutations
- Monthly-review revisions
- Recurring-series overrides

Do not store passwords, setup tokens, bearer tokens, uploaded CSV contents, or complete transaction descriptions in audit messages.

## Backups and recovery

Provide an application-aware SQLite backup command using SQLite's online backup API.

- The command creates a consistent backup without copying a live database file directly.
- Run `PRAGMA integrity_check` on the backup and fail visibly if it does not pass.
- Store backups in a separate Podium managed volume mounted at `/backups`.
- The supplied Podium stack includes a scheduled service using the same image to create a backup daily at 03:15 Europe/Berlin.
- Retain 14 daily backups and 12 monthly backups.
- Use atomic filenames/renames so incomplete backups are never mistaken for valid ones.
- Provide a command to list and verify backups.
- Do not implement one-click in-app restore.
- Document a restore procedure that stops the stack, preserves the failed database, restores a verified backup, and restarts the stack.
- Document that backups on the same Mac do not protect against host/disk loss and should be copied externally.
- Document separate preservation of the Podium stack file and secret file.

## Container and Podium deployment

Deliver:

- A production multi-stage `Dockerfile`
- A `.dockerignore`
- Reproducible `linux/arm64` build instructions
- A native Podium JSON stack definition, not only Docker Compose
- A secret-file example containing names/placeholders only
- Deployment, upgrade, backup, restore, and troubleshooting documentation

The production image should:

- Contain the locked application and bundled assets
- Run without development dependencies
- Run as a non-root user if Podium managed-volume permissions permit it
- Persist only through mounted volumes
- Expose the application on port 8080
- Run schema migrations safely before serving
- Handle SIGTERM cleanly

The Podium stack should use:

- One long-running application service
- A `finanzdaten` managed volume mounted at `/data`
- A `finanzbackups` managed volume mounted at `/backups`
- Podium file secrets for at least `SESSION_SECRET` and `SETUP_TOKEN`
- An explicit `TZ=Europe/Berlin` setting, with the backup schedule's timezone documented and verified
- Readiness and liveness checks against separate endpoints
- Restart policy `always`
- Sensible ARM64 home-server limits, initially 1 CPU, 512 MiB memory, and a small root filesystem
- Managed ingress and stack-local DNS following Podium's documented examples
- Intentional LAN exposure via an editable hostname such as `finanzen.home.arpa`; make the `0.0.0.0` bind explicit and document the security implication
- A scheduled backup service using the same image and volumes

Podium does not build Compose images. Provide a clear workflow for building/loading a local ARM64 OCI image or pulling a tagged image before applying the stack. Validate the final stack with the local Podium validator when it is available.

Provide:

- `/health/live`: process is alive; it must not depend on optional external state
- `/health/ready`: migrations completed, database opens, required directories are writable

Health checks must not expose financial or secret data.

## Security and privacy requirements

- Validate upload size, filename handling, encoding, and CSV structure.
- Do not evaluate spreadsheet formulas or HTML from imported fields.
- Escape imported data in HTML.
- Sanitize Markdown and disallow active content.
- Enforce authorization in every account-scoped service method.
- Use database constraints in addition to application validation.
- Use parameterized database access.
- Do not expose stack traces in production.
- Redact secrets and sensitive transaction content from normal logs.
- Do not send telemetry or financial data to external services.
- Keep runtime network access unnecessary.

## Minimum verification suite

Write deterministic tests that prove:

### Import

- BOM, semicolons, German dates/decimals, non-breaking-space balance metadata, empty fields, long descriptions, and zero-value rows parse correctly.
- All newly imported transactions are uncategorized.
- Reimporting one file inserts zero transactions.
- Overlapping exports insert only new occurrences.
- Two identical rows in one file survive as two transactions and remain two after reimport.
- Unknown layouts, unsupported statuses, malformed rows, and account mismatches commit nothing.
- The raw file is not stored.
- The private sample, when present, passes the expected aggregate checks without printing its data.

### Authorization

- A shared account is visible to both users.
- Each user can see only their own private account.
- Direct HTTP and MCP requests with guessed private IDs do not reveal existence.
- Search, totals, category usage, review counts, and error messages do not leak private data.
- Agent tokens cannot exceed their account or capability scopes.

### Categorization and annotations

- Neither import nor recurring detection assigns a category.
- Human and MCP categorization use the same service logic.
- An agent cannot overwrite or remove a human category.
- Retried idempotent MCP batches do not create duplicate audit events.
- Agent notes append without replacing human notes.
- Tags preserve authorship boundaries.

### Transfers and analytics

- Unique matching transfer sides link without assigning categories.
- Ambiguous candidates remain unlinked.
- A private counterpart is redacted from a shared-only viewer.
- Monthly totals, category trends, recurring overrides, forecast baseline, and uncertainty bands have deterministic fixture-based tests.
- Recurring transactions are not double-counted in the variable forecast.
- Incomplete coverage is visibly reported.

### MCP

- Use the official MCP client in integration tests.
- Initialize a Streamable HTTP session and enumerate all required tools.
- Test pagination, structured errors, capability denial, account denial, optimistic concurrency, batch categorization, notes, tags, analytics, and monthly review revisions.
- Verify revoked and expired tokens fail.

### UI and localization

- First-run setup and login work.
- German is the default.
- Switching a user to English persists.
- Required pages render without missing translation keys.
- A user can import a synthetic DKB file, browse its month, manually categorize one transaction, add a note, inspect trends, and see a saved agent review.
- Key pages have basic accessibility checks and work at desktop and narrow widths.

### Operations

- Fresh-database migrations and upgrades from every committed migration work.
- The online backup verifies and restores to an equivalent database in tests.
- The production image builds for `linux/arm64`.
- The container becomes ready, survives restart with its mounted data, and shuts down cleanly.
- The Podium stack validates when the local Podium validator is available.

## Definition of done

The goal is complete only when:

1. The application is fully implemented rather than scaffolded.
2. The synthetic test suite passes.
3. The private DKB sample is validated locally when available without being copied or exposed.
4. The MCP integration tests pass against the running application.
5. The production ARM64 image builds and passes health checks.
6. The native Podium stack and backup job are present and validated as far as the environment permits.
7. German and English interfaces are complete.
8. Documentation enables a new operator to build, deploy, initialize, connect an MCP agent, import DKB data, back up, upgrade, and restore the application.
9. No feature listed under non-goals has been added.
10. The final report states what was implemented, the exact verification commands and outcomes, any validation that could not run because of the environment, and the paths to the deployment and operations documentation.
