# Architecture and security

Fin is one Python process and one SQLite database. FastAPI serves
server-rendered pages and mounts the official MCP SDK transport. Both adapters
call the same `FinanceService`; neither performs account-scoped database work
around that layer.

## Boundaries

```text
browser + CSRF session ─┐
                       ├─ FinanceService authorization and business rules ─ SQLite
agent + bearer token ───┘
```

One Uvicorn process avoids competing SQLite writers. Connections enable
foreign keys, WAL, a busy timeout, and integer euro cents. Alembic owns schema
versioning.

The frontend uses bundled CSS and framework-free JavaScript. It has no CDN,
analytics, telemetry, bank connection, AI provider, or other runtime network
dependency.

## Privacy

Shared accounts are visible to every active user. A private account is visible
only to its owner. Administrator status permits installation management but
does not bypass ordinary private-account queries.

Every account-scoped service read checks the human owner/shared rule or the
agent token's immutable account scope. Missing and inaccessible objects use
the same `not_found` result. Transfer presentation redacts a linked private
counterpart when the viewer can see only the shared side.

This is application privacy, not cryptographic privacy from the server owner.
The operator can read the SQLite file and backups. Filesystem access,
full-disk encryption, external-backup encryption, and host accounts remain
operator responsibilities.

## Authentication

- Passwords use Argon2id.
- Browser cookies contain a signed opaque session identifier; the server stores
  only its SHA-256 digest, CSRF token, user, and expiry.
- Cookies are HTTP-only and SameSite=Lax. `COOKIE_SECURE` must be true behind
  HTTPS and is false only for intentional HTTP home-LAN use.
- Setup and login forms use separately signed expiring form tokens; all
  authenticated browser mutations require the server-side CSRF token.
- Login attempts are rate-limited by client address and normalized username.
- Agent tokens contain high-entropy random bytes. Plaintext appears once;
  SQLite stores only SHA-256 plus a non-secret prefix.

## Content and audit safety

Jinja auto-escapes imported bank text. Markdown is parsed with raw HTML
disabled and cleaned through a strict allowlist. CSV parsing never evaluates
spreadsheet formulas.

The append-only audit log records actor, action, affected IDs, time, and small
sanitized metadata. It omits passwords, setup/session/bearer tokens, uploaded
files, complete transaction descriptions, notes, and review bodies. Uvicorn
access logging is disabled in production to keep bearer headers and financial
queries out of normal logs.
