# Private Tailscale demo implementation plan

Status: repository implementation complete; private host activation pending

This plan adds a temporary, private demonstration environment for friends and
family. It does not make the live Fin installation public and does not add a
general public-internet deployment profile. The demo reuses the verified Fin
container but has its own synthetic data, secrets, Podium stack, ingress, and
users.

Implementation, deployment, sharing, and teardown are separate actions.
Applying the Podium stack, changing the Tailscale policy, sharing the node, or
deleting demo resources requires explicit operator confirmation at that step.

## Decision and assumptions

- Guests use a browser after installing Tailscale and accepting an individual
  node-share invitation.
- The Mac remains online while the demo is available. Availability is
  best-effort; this is not a production service.
- Tailscale Serve provides private HTTPS. Tailscale Funnel, router port
  forwarding, and a public tunnel are never used.
- The existing synthetic fixture
  [`tests/fixtures/dkb-browser-demo.csv`](../tests/fixtures/dkb-browser-demo.csv)
  is the only transaction source.
- The demo derives a small image from the verified Fin image solely to install
  a fail-closed outbound firewall. Do not add a native app, a second web
  architecture, a public deployment mode, a read-only role, or an automated
  demo-reset feature unless operation proves one is necessary.
- Each guest receives a non-administrator Fin account. The operator keeps the
  only administrator credential and does not create MCP tokens.
- Tailscale's current Personal plan and node-sharing limits are sufficient for
  the intended group. Recheck the limits before rollout.

Relevant Tailscale documentation:

- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve)
- [Node sharing](https://tailscale.com/kb/1084/sharing)
- [Grants and policy tests](https://tailscale.com/docs/features/access-control/grants)
- [Current free-plan limits](https://tailscale.com/docs/reference/free-plans-discounts)

## Governing security invariant

Compromise or misuse of the demo must not disclose or modify the live Fin
database, backups, secrets, container volumes, or other home-LAN services.

The intended request path is:

```text
guest browser
  -> private Tailscale connection to TCP 443
  -> Tailscale Serve on the Mac
  -> 127.0.0.1:<dedicated demo port>
  -> finanzplaner-demo Podium stack
  -> finanzdaten-demo volume containing synthetic data only
```

There must be no route from the demo stack to `finanzdaten`,
`finanzbackups`, the live Fin ingress, or other RFC1918/ULA home-network
destinations. Tailscale access is an additional boundary, not a substitute for
application authentication or workload isolation.

## Success criteria

1. An invited guest can open the demo over private Tailscale HTTPS and sign in
   with a non-admin Fin account.
2. An uninvited identity cannot reach the demo.
3. A guest can reach only the selected node's HTTPS port; SSH, the Podium host
   port, the live Fin port, and other services remain unreachable.
4. The demo stack contains only synthetic data and uses no live volume, backup,
   session secret, setup token, or MCP token.
5. The demo workload cannot initiate connections to the live stack or home-LAN
   destinations.
6. `COOKIE_SECURE=true`, the exact Tailscale HTTPS hostname is trusted, and
   first-run setup returns `404` before Tailscale sharing is enabled.
7. Stopping Serve immediately removes remote access. Removing the demo stack
   affects only explicitly named demo resources.
8. Focused tests and the repository's documented local checks pass.

## Phase 0 — Preflight and threat-boundary proof

1. Record, without committing private identifiers:
   - the Mac's Tailscale DNS name;
   - the Tailscale identities that will receive invitations;
   - whether HTTPS certificates are enabled for the tailnet;
   - whether Tailscale Serve already owns TCP 443;
   - the existing Serve/Funnel configuration and tailnet policy.
2. Export or otherwise preserve the current Tailscale policy before editing it.
   Do not replace unrelated grants or tests.
3. Confirm that `tailscale funnel status` is disabled on the node. If Funnel is
   in use for another service, stop and resolve the port/ownership conflict
   rather than overwriting it.
4. Determine how Podium can enforce outbound isolation for this stack. The
   required policy is deny all demo-initiated network traffic, or at minimum
   deny:
   - the live Podium stack and its ingress;
   - the Mac host and local gateway;
   - all home RFC1918 and ULA subnets;
   - other Podium stacks.
5. Prove the policy with negative connection tests from the demo workload.
   Merely observing that cross-stack names do not resolve is insufficient.

Security gate: if Podium cannot provide an enforceable and testable outbound
boundary, do not share a Podium workload running on the home Mac. Use a
dedicated isolated VM for the demo/Tailscale node, with a firewall that denies
home-LAN routes, or revisit a remote synthetic host. Do not weaken this gate to
keep the setup simple.

## Phase 1 — Add the isolated demo stack

Add `podium/finanzplaner.demo.stack.json`, modeled on the acceptance stack but
with no scheduled backup service.

Required stack contract:

- stack name `finanzplaner-demo`;
- only one `app` service using the derived
  `localhost/finanzplaner-demo:1.2.0-rc.1` image;
- volume name `finanzdaten-demo`, mounted only at `/data`;
- no `finanzdaten`, `finanzbackups`, acceptance, or host-directory mounts;
- a dedicated host port, tentatively `18082`, bound to `127.0.0.1` only;
- an ingress route for the exact Tailscale DNS hostname selected in preflight;
- `ENVIRONMENT=production`;
- `COOKIE_SECURE=true` because the browser-facing connection is HTTPS;
- `TRUSTED_HOSTS` limited to the Tailscale hostname plus the loopback names
  needed for local provisioning and health checks;
- separate `SESSION_SECRET` and `SETUP_TOKEN` references;
- the existing non-root runtime user, resource limits, readiness check,
  liveness check, and restart policy;
- the outbound isolation established in Phase 0 by `Dockerfile.demo` and
  `docker/demo-entrypoint.sh`.

Add a focused assertion in `tests/test_operations.py` proving those properties,
especially the loopback bind, secure cookie, exact demo-only volume set, lack
of a backup service, and lack of production resource names.

Verification:

```sh
uv run pytest tests/test_operations.py
uv run ruff check src tests migrations scripts
```

Do not apply the stack in this phase without separate operator confirmation.

## Phase 2 — Provision synthetic data before sharing

1. Create a demo-only secret file under the demo stack's Podium configuration
   directory. Generate new random values; do not copy the live secret file.
2. Validate the synthetic CSV before deployment:

   ```sh
   uv run pytest tests/test_import.py::test_committed_browser_demo_fixture_is_valid_and_synthetic
   ```

3. With operator confirmation, validate and apply only
   `finanzplaner.demo.stack.json`.
4. Keep Tailscale Serve disabled. Reach the demo only through its loopback
   ingress while provisioning it.
5. Complete first-run setup with the private demo setup token and create the
   operator-only administrator.
6. Import only `tests/fixtures/dkb-browser-demo.csv` into a shared account.
7. Create one non-admin account per guest, with unique passwords delivered
   out-of-band. Do not share the administrator password or setup token.
8. Verify that `/setup` returns `404`, no agent tokens exist, and every account
   and transaction is synthetic.
9. Restart the demo stack and verify that its SQLite data persists only in
   `finanzdaten-demo`.

Provisioning remains manual for the first implementation. This avoids adding a
demo mode to application code and makes the moment at which sharing becomes
possible explicit. If repeatable resets later become necessary, propose a
separate, deterministic seed command with tests; do not copy a prepared
database from the live installation.

## Phase 3 — Configure private Tailscale access

1. Configure Tailscale Serve to proxy private HTTPS on the selected node to the
   loopback-only Podium demo port. Do not enable Funnel.
2. Preserve existing tailnet grants and add the narrowest rule for invited
   identities. The intended policy permits shared users to reach only TCP 443
   on the selected node. Prefer explicit email identities while the invitation
   set is small; otherwise use `autogroup:shared` with the same destination and
   port restriction.
3. Add policy tests for each security claim:
   - invited identity accepts the demo node on TCP 443;
   - invited identity is denied TCP 22, 8080, and the Podium host port;
   - invited identity is denied the live Fin service and other tailnet nodes;
   - an uninvited identity is denied TCP 443 on the demo node.
4. Validate the policy before saving it. Inspect `tailscale serve status` and
   `tailscale funnel status` afterward.
5. Send individual node-share invitations. Do not use a reusable public share
   link.

The exact Serve command and destination selector must be filled in from the
preflight results. Do not commit the Mac's Tailscale DNS name, IP address,
guest email addresses, or policy export to this repository.

## Phase 4 — End-to-end acceptance

Run the checks from a genuinely separate invited device, not only from the Mac:

1. HTTPS succeeds at the Tailscale Serve URL with a valid certificate.
2. HTTP is not exposed and the session cookie is `Secure`, HTTP-only, and
   SameSite=Lax.
3. Login succeeds only with the guest's non-admin Fin account.
4. Overview, transactions, annual report, forecast, and transaction detail
   render with the synthetic account at desktop and mobile widths.
5. Administrator pages and mutations are denied to the guest.
6. `/setup` returns `404`; unauthenticated `/mcp` access is denied; no MCP token
   is issued for the demo.
7. TCP 22, 8080, the Podium host port, the live Fin port, and another tailnet
   node are unreachable from the guest device.
8. The demo workload's negative egress tests from Phase 0 still fail as
   expected.
9. The live stack remains healthy and its stack definition and volume mapping
   are unchanged.

Then run the documented repository checks:

```sh
uv run pytest
uv run ruff check src tests migrations scripts
uv run python scripts/check_markdown_links.py
```

Record only aggregate results and redacted configuration evidence. Do not
capture guest emails, Tailscale IPs, secrets, passwords, or household data in
the repository or test artifacts.

## Phase 5 — Documentation and operation

After successful acceptance, add a concise "Private Tailscale demo" section to
`docs/operator-guide.md` and link it from `docs/index.md`. Document only the
verified commands and replace private hostnames and identities with
placeholders.

Operating rules:

- keep the live and demo URLs visually distinct;
- tell guests not to upload real bank exports or enter personal notes;
- keep the demo available only for the agreed window;
- inspect normal health and logs without enabling request-body, database, or
  access logging;
- add and remove guests individually;
- treat all demo mutations as disposable and provide no backup guarantee;
- re-run policy and negative-access tests after any Tailscale or Podium change.

## Disable, rollback, and teardown

Emergency disable order:

1. Turn off the demo's Tailscale Serve configuration.
2. Revoke every node share.
3. Confirm TCP 443 is no longer reachable from a previously invited device.
4. Stop the `finanzplaner-demo` stack without deleting volumes while inspecting
   an incident.
5. Restore the preserved tailnet policy if its demo-only change caused a
   regression.

Normal teardown, with explicit operator confirmation:

1. Turn off Serve and verify Funnel remains disabled.
2. Revoke all invitations and accepted shares.
3. Stop the exact `finanzplaner-demo` stack.
4. Delete only `finanzdaten-demo` after confirming it contains synthetic data.
5. Remove the demo-only secret file through an approved recoverable method
   where available.
6. Verify the live `finanzplaner` stack is healthy.

Never use an unqualified `podium down --volumes` command. Every destructive
command must name `finanzplaner-demo`, and its resolved targets must be reviewed
before execution.

## Expected repository changes

- `podium/finanzplaner.demo.stack.json`
- `Dockerfile.demo`
- `docker/demo-entrypoint.sh`
- `tests/test_operations.py`
- `docs/operator-guide.md`
- `docs/index.md`

No application source or schema change is expected. If Phase 0 or end-to-end
acceptance demonstrates that a code change is necessary, stop and propose the
smallest separate change with its own tests and documentation impact.

## Definition of done

The work is complete only when the success criteria are evidenced from an
invited external device, the outbound isolation gate passes, all repository
checks pass, verified operating and teardown instructions are documented, and
remote access can be removed without touching the live Fin stack or its data.
