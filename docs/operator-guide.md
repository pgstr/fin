# Fin operator guide

This guide deploys one local Fin installation on an Apple-silicon
Podium host. It intentionally assumes a trusted home network, not public
internet exposure.

## 1. Requirements

- Podium on an Apple-silicon Mac that satisfies Podium's compatibility guide
- Docker Buildx, another OCI-compatible ARM64 builder, or a CI builder
- local DNS for `finanzen.home.arpa`
- the checked-in `uv.lock`, stack file, and this repository

Fin needs no runtime internet access and sends no telemetry.

## 2. Build and load the ARM64 image

From the repository root:

```sh
mkdir -p dist
docker buildx build \
  --platform linux/arm64 \
  --tag localhost/finanzplaner:1.1.0 \
  --output type=oci,dest=dist/finanzplaner-1.1.0-arm64.oci.tar \
  .
podium load dist/finanzplaner-1.1.0-arm64.oci.tar
```

Podium does not build Compose projects. The stack uses the exact image name
`localhost/finanzplaner:1.1.0`; if the builder records another reference,
change the stack's two `image` fields to the reference printed by
`podium load`.

For the `1.1.0` release build verified on 2026-07-31, the ARM64 OCI manifest
digest was
`sha256:300e17152721342bc5736f833789e1a70128030969b64f2c8083cb7b94d96add`.
The exported OCI archive SHA-256 was
`0ab97046ea557bc7b69bef21894802930afbb2a13ef164df30b4b96deb5a2a57`.
Rebuilds must be treated as different artifacts even when they use the same
source and tag.

## 3. Create file secrets

Generate values without printing them into shell history when possible. Copy
`podium/secrets.env.example` to a temporary location outside the repository,
replace both placeholders, and install it with owner-only permissions:

```sh
mkdir -p ~/.podium/finanzplaner
install -m 600 /secure/path/finanzplaner-secrets.env \
  ~/.podium/finanzplaner/secrets.env
```

`SESSION_SECRET` must be random and at least 32 characters. `SETUP_TOKEN` is
used only while the database has no administrator. The application ignores it
after first-run setup, but preserve the secret file for reproducible recovery.
Never commit the populated file.

## 4. Validate and apply

Review these intentional defaults in
`podium/finanzplaner.stack.json` before applying:

- hostname `finanzen.home.arpa`;
- HTTP port 8080;
- `COOKIE_SECURE=false`, appropriate only for HTTP on a trusted home network;
- ingress bind `0.0.0.0`, which exposes the service to every reachable LAN
  interface;
- 1 CPU, 512 MiB memory, and a 1 GiB root filesystem.

Configure local DNS so `finanzen.home.arpa` resolves to the Podium host. Then:

```sh
podium pull docker.io/library/caddy:2-alpine
podium pull docker.io/coredns/coredns:1.12.4
podium validate podium/finanzplaner.stack.json
podium apply podium/finanzplaner.stack.json
podium ps --stack finanzplaner
curl --resolve finanzen.home.arpa:8080:127.0.0.1 \
  http://finanzen.home.arpa:8080/health/ready
```

For a temporary host-only check, change ingress `bindAddress` to `127.0.0.1`.
For HTTPS ingress, terminate TLS in an approved local proxy, set
`COOKIE_SECURE=true`, and update `TRUSTED_HOSTS`.

### Isolated acceptance stack

Never use the live `finanzplaner` stack for release acceptance. The checked-in
`podium/finanzplaner.acceptance.stack.json` uses a separate stack name,
separate managed volumes, loopback-only port 18081, and the hostname
`finanzplaner-acceptance.home.arpa`.

Install a generated test-only secret file at
`~/.podium/finanzplaner-acceptance/secrets.env`, then run:

```sh
podium validate podium/finanzplaner.acceptance.stack.json
podium apply podium/finanzplaner.acceptance.stack.json
podium ps --stack finanzplaner-acceptance
curl --resolve finanzplaner-acceptance.home.arpa:18081:127.0.0.1 \
  http://finanzplaner-acceptance.home.arpa:18081/health/ready
podium exec --stack finanzplaner-acceptance app -- \
  getent hosts app.podium.local
podium restart --stack finanzplaner-acceptance app
podium describe --stack finanzplaner-acceptance app
podium describe --stack finanzplaner-acceptance backup
```

After the acceptance and recovery checks, remove only the isolated resources:

```sh
podium down --stack finanzplaner-acceptance --volumes -y
```

## 5. First-run setup and first import

Open `http://finanzen.home.arpa:8080`, enter the setup token, and create the
first administrator with a password of at least 12 characters. The setup route
becomes unavailable immediately afterward.

Choose **DKB-Export importieren**. For the first file, leave the expected
existing account empty and provide a display name plus `Gemeinsam` or `Privat`.
The IBAN inside the CSV is authoritative. Fin validates the complete
file before one atomic commit and never retains the uploaded raw file.

The application displays only aggregate import results. Reimporting the same
file is safe.

## 6. Health and routine operation

- `/health/live` proves that the process responds; it intentionally does not
  depend on the database.
- `/health/ready` checks migrations, database access, and writable data and
  backup directories.

Useful Podium commands:

```sh
podium ps --stack finanzplaner
podium describe --stack finanzplaner app
podium logs --stack finanzplaner --tail 100 app
podium events --stack finanzplaner
podium exec --stack finanzplaner app -- \
  gosu finanzplaner finanzplaner backup list
```

Normal logs omit access payloads and bearer tokens. Do not enable verbose
database or request-body logging in production.

## 7. Scheduled backups

The `backup` scheduled service runs the same image at `15 3 * * *`. Podium
evaluates cron expressions in the **Podium host's current timezone**. The
container also sets `TZ=Europe/Berlin` so filenames and human diagnostics use
the same zone.

Before relying on the schedule, verify:

```sh
date +%Z
podium describe --stack finanzplaner backup
```

The host timezone must be Europe/Berlin. Podium's displayed next run should be
03:15 local time, including after daylight-saving transitions.

The backup command uses SQLite's online backup API, runs
`PRAGMA integrity_check`, then atomically renames the completed file. It keeps
14 daily backups and the first verified backup from each of the latest 12
months. Files live in the separate `finanzbackups` managed volume.

Create and verify an extra backup:

```sh
podium exec --stack finanzplaner app -- \
  gosu finanzplaner /usr/bin/env \
  DATABASE_PATH=/data/finanzplaner.db BACKUP_DIR=/backups \
  /app/.venv/bin/finanzplaner backup create
podium exec --stack finanzplaner app -- \
  gosu finanzplaner /usr/bin/env \
  DATABASE_PATH=/data/finanzplaner.db BACKUP_DIR=/backups \
  /app/.venv/bin/finanzplaner backup list
```

Same-Mac backups do not protect against host theft or disk failure. Copy
verified backups to encrypted external storage. Preserve the stack file and
the populated secret file separately as well.

## 8. Upgrade and rollback

Before an upgrade:

```sh
podium exec --stack finanzplaner app -- \
  gosu finanzplaner /usr/bin/env \
  DATABASE_PATH=/data/finanzplaner.db BACKUP_DIR=/backups \
  /app/.venv/bin/finanzplaner backup create
podium exec --stack finanzplaner app -- \
  gosu finanzplaner /usr/bin/env \
  DATABASE_PATH=/data/finanzplaner.db BACKUP_DIR=/backups \
  /app/.venv/bin/finanzplaner backup list
```

Build and load a new immutable tag, update both image references in the stack,
then:

```sh
podium validate podium/finanzplaner.stack.json
podium diff --stack finanzplaner
podium reload --stack finanzplaner
podium ps --stack finanzplaner
```

The entrypoint runs Alembic before the web server accepts traffic. Retain the
previous image tag and a verified pre-upgrade backup. Application rollback is
an image-reference change; database rollback requires the restore procedure
below when a migration is not backward-compatible.

## 9. Restore a verified backup

There is deliberately no in-app restore button.

1. Verify the selected backup and record its full path.
2. Stop the stack without deleting volumes.
3. Preserve the failed database, WAL, and SHM files under a timestamped name.
4. Copy the verified backup to `finanzplaner.db` in the `finanzdaten` volume.
5. Validate the stack and apply it again.
6. Confirm readiness, login, import history, and the latest balance.

On the Podium host:

```sh
podium down --stack finanzplaner
cd ~/.podium/finanzplaner/volumes/finanzdaten
failed_dir="failed-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$failed_dir"
mv finanzplaner.db finanzplaner.db-wal finanzplaner.db-shm \
  "$failed_dir"/ 2>/dev/null || true
cp ~/.podium/finanzplaner/volumes/finanzbackups/daily/SELECTED.sqlite3 \
  finanzplaner.db
chmod 600 finanzplaner.db
sqlite3 finanzplaner.db 'PRAGMA integrity_check;'
podium validate /absolute/path/to/podium/finanzplaner.stack.json
podium apply /absolute/path/to/podium/finanzplaner.stack.json
```

The integrity command must print exactly `ok`. Do not use
`podium down --volumes`; that command destroys both data and backups.
Keep the restored database owned by the Podium host user; Podium maps that host
ownership into its VM. Do not change the host file to container UID/GID 10001.
Perform recovery first against the isolated acceptance volumes, and verify
login, import history, transactions, monthly reviews, and the latest balance
before touching a live stack.

## 10. Troubleshooting

- **Not ready:** inspect `podium logs`, confirm `/data` and `/backups` are
  writable, and verify the database path.
- **Setup token rejected:** use the exact value in
  `~/.podium/finanzplaner/secrets.env`. If an admin already exists, setup is
  intentionally disabled.
- **Import rejected:** confirm it is a DKB Girokonto UTF-8 CSV with booked
  rows. Pending statuses and separate Visa exports are unsupported.
- **Hostname fails:** confirm local DNS, `TRUSTED_HOSTS`, managed ingress, and
  the LAN bind.
- **Agent gets 401:** the bearer token is mistyped, expired, revoked, or its
  user is disabled.
- **Agent receives `not_found`:** the object may not exist or may be outside
  its account scope; these cases are intentionally indistinguishable.
- **Backup did not run:** verify the host timezone and inspect the scheduled
  service's last run and events.
