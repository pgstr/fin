# Fin operator guide

This guide deploys one local Fin installation on an Apple-silicon
Podium host. It intentionally assumes a trusted home network, not public
internet exposure.

## 1. Requirements

- Podium on an Apple-silicon Mac that satisfies Podium's compatibility guide
- Docker Buildx or another OCI-compatible ARM64 builder
- local DNS for `finanzen.home.arpa`
- the checked-in `uv.lock`, stack file, and this repository

Fin needs no runtime internet access and sends no telemetry.

## 2. Build and load the ARM64 image

From the repository root:

```sh
mkdir -p dist
docker buildx build \
  --platform linux/arm64 \
  --tag localhost/finanzplaner:1.2.0-rc.2 \
  --output type=oci,dest=dist/finanzplaner-1.2.0-rc.2-arm64.oci.tar \
  .
podium load dist/finanzplaner-1.2.0-rc.2-arm64.oci.tar
```

Podium does not build Compose projects. The stack uses the exact image name
`localhost/finanzplaner:1.2.0-rc.2`; if the builder records another reference,
change the stack's two `image` fields to the reference printed by
`podium load`.

For the `1.1.0` release build verified on 2026-07-31, the ARM64 OCI manifest
digest was
`sha256:300e17152721342bc5736f833789e1a70128030969b64f2c8083cb7b94d96add`.
The exported OCI archive SHA-256 was
`0ab97046ea557bc7b69bef21894802930afbb2a13ef164df30b4b96deb5a2a57`.
Rebuilds must be treated as different artifacts even when they use the same
source and tag.

For the `1.2.0-rc.1` prerelease build verified on 2026-07-31, the ARM64 OCI
manifest digest is
`sha256:2e74869625175a71f9390577f443a31aa3e70b1f6036a4441c90d83939e00a0c`.
The exported OCI archive SHA-256 is
`cf9afdd1b22eecf92f3d0898dd3f4a294d0c2e7a147f1c82ab24ae8f7214f9bd`.

For the `1.2.0-rc.2` prerelease build (interface redesign) verified on
2026-07-31, the ARM64 OCI manifest digest is
`sha256:d56f31b00f3732f18327b7e46951735d929b3e366b53c0683ecccc95c813de9c`.
The exported OCI archive SHA-256 is
`10ca27c205c0401c4fdbea2bee3aba2e1a30a40986274d8f6bdf92d5b828830d`.
This build carries no Alembic revision beyond `20260731_0003`, so the
entrypoint's `alembic upgrade head` is a no-op against an `rc.1` database.

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

### Private Tailscale demo

The demo is a separate, synthetic-only Podium stack reached through Tailscale
Serve. It does not expose the live stack, open a router port, or use Tailscale
Funnel. Guests still authenticate to Fin with non-administrator accounts.

The checked-in `podium/finanzplaner.demo.stack.json` is a template. Its
`demo-node.example.ts.net` hostname must be replaced in an untracked copy with
the M1 Pro's actual Tailscale DNS name. Never commit the tailnet name, guest
identities, Tailscale policy export, or populated secrets.

#### Host dependency

Use Tailscale's standalone macOS package, which Tailscale recommends over its
App Store and command-line-only variants. The package installs
`/Applications/Tailscale.app`; its bundled CLI is invoked below with
`TAILSCALE_BE_CLI=1`. Installing the system extension, VPN configuration, and
signing in require interactive approval on the Mac.

The M1 Pro installation performed on 2026-07-31 uses Tailscale `1.98.10` from
the stable package server. Its package SHA-256 is
`c2eaf5f660ad45a64d1ba43ee72401029a5cb06e6d148c5e90a987a6f546bc58`.
The package installation completed non-interactively; macOS system-extension
approval, VPN configuration approval, and tailnet sign-in remain explicit
interactive operator actions.

```sh
curl --fail --show-error --location \
  --output /private/tmp/Tailscale-1.98.10-macos.pkg \
  https://pkgs.tailscale.com/stable/Tailscale-1.98.10-macos.pkg
shasum -a 256 /private/tmp/Tailscale-1.98.10-macos.pkg
sudo installer -pkg /private/tmp/Tailscale-1.98.10-macos.pkg -target /
open -a Tailscale
```

Compare the printed digest exactly before running `installer`. In the Tailscale
UI, approve the system extension and VPN configuration, sign in, enable HTTPS
certificates for the tailnet, and leave Funnel disabled. The current official
[macOS installation](https://tailscale.com/docs/install/mac),
[system-extension](https://tailscale.com/docs/concepts/macos-sysext), and
[uninstall](https://tailscale.com/docs/features/client/uninstall) instructions
remain authoritative.

To remove the dependency later, first disable Serve and revoke every node
share, sign out, use Tailscale's **Uninstall** action, and follow the official
standalone macOS cleanup instructions for the VPN configuration and retained
state. Do not install another macOS Tailscale variant alongside the standalone
application.

#### Build and load the egress-blocked image

`Dockerfile.demo` derives from the verified Fin image and adds only `iptables`
plus `docker/demo-entrypoint.sh`. Before Fin starts, that entrypoint permits
loopback traffic and replies to established ingress connections, then rejects
every new IPv4 and IPv6 connection initiated by the demo process. Failure to
install the rules prevents the application from starting.

Load the verified base OCI archive into the builder, then export the derived
ARM64 image:

```sh
docker image load --input dist/finanzplaner-1.2.0-rc.2-arm64.oci.tar
docker buildx build \
  --platform linux/arm64 \
  --file Dockerfile.demo \
  --tag localhost/finanzplaner-demo:1.2.0-rc.1 \
  --output type=oci,dest=dist/finanzplaner-demo-1.2.0-rc.1-arm64.oci.tar \
  .
```

Copy the archive to the M1 Pro through the existing administrative SSH path
and load it into Podium. Treat every rebuild as a distinct artifact and record
its archive and manifest digests with the acceptance result.

For the image built and loaded on 2026-07-31, the ARM64 OCI manifest digest is
`sha256:4c496d3a021e764d73c5c2ad38440d439172a33c41ac90168a0d88dc7a4425c6`.
The exported archive SHA-256 is
`99f552e8772af7f3a1c9f57109a2c6db4043c436c75b1120fffe40f8f3cde9e1`.
The local smoke test proved readiness through mapped loopback ingress, default
`DROP` policies for IPv4 and IPv6 output, and rejection of a new outbound
connection. The checked-in stack template also passed `podium validate` on the
M1 Pro without being applied.

#### Render and validate the private stack

On the M1 Pro, obtain the DNS name without printing the rest of the Tailscale
status document:

```sh
TAILSCALE_BE_CLI=1 /Applications/Tailscale.app/Contents/MacOS/Tailscale \
  status --json | jq -r '.Self.DNSName'
```

Set `DEMO_TAILSCALE_HOST` to that name without a trailing dot. Render an
untracked stack file with `jq` rather than editing the committed template:

```sh
DEMO_TAILSCALE_HOST=demo-node.example-tailnet.ts.net
demo_stack_path=/private/tmp/finanzplaner.demo.stack.json
jq --arg host "$DEMO_TAILSCALE_HOST" \
  '.services[0].env.TRUSTED_HOSTS = ($host + ",localhost,127.0.0.1")
   | .ingress.routes[0].host = $host' \
  podium/finanzplaner.demo.stack.json > "$demo_stack_path"
podium validate "$demo_stack_path"
```

The rendered stack must retain all of these properties:

- name `finanzplaner-demo`;
- image `localhost/finanzplaner-demo:1.2.0-rc.1`;
- only the volume `finanzdaten-demo` mounted at `/data`;
- no backup service or production/acceptance volume;
- `COOKIE_SECURE=true`;
- host port 18082 bound only to `127.0.0.1`;
- no Podium DNS service.

Create new demo-only secrets. Do not copy the live secret file:

```sh
mkdir -p ~/.podium/finanzplaner-demo
install -m 600 /secure/path/finanzplaner-demo-secrets.env \
  ~/.podium/finanzplaner-demo/secrets.env
```

Applying the stack is a deployment and requires explicit operator
confirmation:

```sh
podium apply "$demo_stack_path"
podium ps --stack finanzplaner-demo
curl --resolve "$DEMO_TAILSCALE_HOST:18082:127.0.0.1" \
  "http://$DEMO_TAILSCALE_HOST:18082/health/ready"
podium exec --stack finanzplaner-demo app -- iptables -S OUTPUT
podium exec --stack finanzplaner-demo app -- ip6tables -S OUTPUT
```

Both firewall listings must show a default `DROP` policy, a loopback allow, and
an `ESTABLISHED,RELATED` allow. From the demo workload, connections to the live
Fin address, the Mac, the local gateway, and another RFC1918/ULA address must
time out or be rejected. If any succeeds, stop the demo and do not configure
Serve.

#### Provision before sharing

Keep Serve disabled while provisioning. Open the loopback-only URL on the M1
Pro, complete setup with the private demo setup token, import only
`tests/fixtures/dkb-browser-demo.csv`, and create one non-admin user per guest.
Keep the only administrator password and never create an MCP token.

Before continuing, verify `/setup` returns `404`, unauthenticated `/mcp` access
is denied, the demo survives a restart, and only `finanzdaten-demo` is mounted.
Guests must be told not to upload real exports or enter personal information.

#### Enable Serve and restrict shared users

First preserve the current tailnet policy and inspect it for broad rules whose
source is `*`; such rules also apply to shared users. Add an explicit grant for
each guest identity and the M1 Pro's Tailscale IP, limited to TCP 443. Add policy
tests proving that TCP 443 is accepted while TCP 22, 8080, and 18082 and other
nodes are denied. Merge these entries into the existing policy; do not replace
unrelated grants or tests.

After the policy validates, enable private Serve:

```sh
TAILSCALE_BE_CLI=1 /Applications/Tailscale.app/Contents/MacOS/Tailscale \
  serve --bg http://127.0.0.1:18082
TAILSCALE_BE_CLI=1 /Applications/Tailscale.app/Contents/MacOS/Tailscale \
  serve status
TAILSCALE_BE_CLI=1 /Applications/Tailscale.app/Contents/MacOS/Tailscale \
  funnel status
```

The Serve status must show private HTTPS forwarding to loopback. Funnel must
remain disabled. Send individual node-share invitations from the Tailscale
admin console; do not use a reusable invitation link.

From an invited external device, verify HTTPS and guest login, then verify that
SSH, ports 8080 and 18082, the live Fin service, and another tailnet node remain
unreachable.

#### Disable and remove the demo

Disable remote access before stopping or deleting the stack:

```sh
TAILSCALE_BE_CLI=1 /Applications/Tailscale.app/Contents/MacOS/Tailscale \
  serve --https=443 off
```

Revoke every node share and confirm a formerly invited device can no longer
connect. `podium down --stack finanzplaner-demo` preserves the synthetic volume
for investigation. Deleting it is destructive and requires separate operator
confirmation:

```sh
podium down --stack finanzplaner-demo --volumes -y
```

Never run an unqualified `podium down --volumes`. Confirm the live
`finanzplaner` stack remains healthy after teardown.

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

## Related engineering contracts

See the [development map](development.md) for local release checks, the
[architecture and security guide](architecture.md) for runtime boundaries, and
the [domain model](domain-model.md) for migration ownership.
[`test_operations.py`](../tests/test_operations.py),
[`test_backup.py`](../tests/test_backup.py), and
[`container_smoke.py`](../scripts/container_smoke.py) prove the checked-in
operational contract. Live deployment, publication, backup restoration, and
household-data validation still require explicit operator confirmation.
