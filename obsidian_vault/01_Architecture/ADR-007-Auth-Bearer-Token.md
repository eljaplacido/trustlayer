---
adr: 007
status: accepted
date: 2026-05-24
tags: [architecture, phase-6, security, auth, http-api]
supersedes: []
extends: ["[[ADR-004-Cynepic-Guardian-Policy-Engine]]", "[[ADR-006-Phase-5-Dashboard-MCP]]"]
---

# ADR-007 — Bearer-token auth on the guardian + trace store

## Context

The Phase-5 trace-store API ([[ADR-006-Phase-5-Dashboard-MCP]]) and the
Phase-4 guardian HTTP surface ([[ADR-004-Cynepic-Guardian-Policy-Engine]])
are reachable on `127.0.0.1:8089` without any authentication. ADR-006
noted this as a follow-up and justified the gap with "loopback-only for
v0." That assumption breaks the moment someone:

- exposes the sidecar past loopback (reverse-proxy, Docker bridge,
  Tailscale, k3s), which is the natural deployment path;
- runs the sidecar on a multi-tenant host where other local processes
  could forge events;
- ships TrustLayer as a managed service.

For TrustLayer to read as a credible open standard, the wire-level
protocol needs at least one documented auth mechanism, even if every v0
deployment leaves it disabled.

## Decision

### Mechanism: a single shared bearer token via environment variable.

- New env var: `TRUSTLAYER_API_TOKEN`. If set, the sidecar requires
  `Authorization: Bearer <token>` on every request **except**
  `GET /healthz`. If unset, the sidecar accepts unauthenticated
  requests as today (preserving the local-dev experience).
- Comparison is constant-time (`subtle::ConstantTimeEq`) to avoid
  timing oracles.
- On missing / malformed / wrong token the sidecar returns
  `401 Unauthorized` with `WWW-Authenticate: Bearer realm="trustlayer"`
  and an empty body.
- `/healthz` is intentionally unauthenticated so liveness probes and
  load balancers work without secrets.

### Scope: every route, including reads.

Read routes (`GET /v1/events`, `/v1/sessions`, `/v1/reflections`) are
authenticated too. The trace store is privacy-sensitive — event
payloads contain prompts, tool arguments, and verdicts — so "reads are
free" would leak the entire session history of any agent that ever ran.
The dashboard already passes a header through the new SDK contract
(see below), so the UX cost is zero.

### Client-side contract

Every SDK that calls the sidecar gains an optional `token` parameter
(env-overridable):

- **Python:** `GuardianClient(token=...)` and
  `TrustLayerClient(token=...)`. Reads `TRUSTLAYER_API_TOKEN` from the
  process environment when not passed explicitly.
- **TypeScript:** `new GuardianClient({ token, ... })`,
  `new TrustLayerClient({ token, ... })`. Same env fallback.
- **MCP server:** propagates `TRUSTLAYER_API_TOKEN` to both clients
  transparently.
- **Dashboard:** reads `VITE_TRUSTLAYER_API_TOKEN` at build time. For
  v0 the dashboard is operator-facing and the token sits in the same
  `.env` as `VITE_TRUSTLAYER_BASE_URL`.

If the token is set on the server but missing on the client, every
request fails with `401`. This is the desired failure mode for v0 —
loud rather than silent — and matches how every other HTTP-bearer API
behaves.

### Non-decisions (explicitly deferred)

- **mTLS, OAuth2, JWT, OIDC** — out of scope. A single bearer token
  covers the "front this with a reverse proxy that adds real auth"
  story. Anything more sophisticated belongs in a future ADR.
- **Per-agent or per-tenant scoping.** The token is a deployment-level
  secret, not an identity. Multi-tenant deployments will need a
  follow-on ADR that probably introduces a real identity model.
- **Token rotation API.** Operator-driven: stop the sidecar, change
  the env, restart. Hot-reload of the token would interact with the
  Phase-6 policy hot-reload work ([[ADR-009-Policy-Hot-Reload]]) — if
  we want it, it should land in the same shape.
- **Encrypting events in flight.** Out of band: terminate TLS at the
  reverse proxy. The sidecar binds loopback by default.

## Implementation sketch

- `core-rs/src/auth.rs` (new) — Axum `from_fn_with_state` middleware.
  Reads the configured token from `AppState`; skips when
  `Option::None`. Constant-time compare via the `subtle` crate.
- `core-rs/src/server.rs` — wire the middleware via
  `router.route_layer(...)` on every route except `/healthz`.
- `core-rs/src/bin/guardian.rs` — load `TRUSTLAYER_API_TOKEN`, log
  a single startup line stating whether auth is enabled (without
  printing the secret).
- Python SDK: `GuardianClient` + `TrustLayerClient` accept `token:
  str | None = None` and inject `Authorization: Bearer ...` into
  the httpx client when set; env fallback in `__init__`.
- TypeScript SDK: same shape, env fallback via
  `process.env.TRUSTLAYER_API_TOKEN` (Node) or `import.meta.env`
  (Vite). The dashboard already has Vite, so it goes through the
  build-time env.
- MCP server: read the env once at `main()`, pass to both clients.

## Tests

- **Rust:** integration tests on `build_router` confirming
    (a) no-token-configured ⇒ unauthenticated requests succeed,
    (b) token-configured + correct ⇒ 200,
    (c) token-configured + missing ⇒ 401 with the right
        `WWW-Authenticate` header,
    (d) token-configured + wrong ⇒ 401,
    (e) `/healthz` is always reachable.
- **Python:** `GuardianClient` and `TrustLayerClient` set the
  `Authorization` header iff configured; env fallback works; absence
  produces no header.
- **TypeScript:** same three assertions through the `fetch` stub.
- **MCP server:** new unit test that the propagation reaches both
  client constructors.

## Consequences

- **+** Sidecar can be safely exposed past loopback once the operator
  sets the env var.
- **+** Public protocol now has a documented auth story; the
  compatibility matrix in `docs/VERSIONING.md` can call out the v0
  bearer behaviour without hand-waving.
- **+** The "open by default for dev" UX survives: nothing changes for
  local developers who don't set the env var.
- **−** Single shared token has no per-client revocation. Acceptable
  for v0; rotation is "change the env, restart the sidecar."
- **−** Operators who *want* loopback-only without auth have no
  enforcement — they get convention, not policy. A future ADR could
  add a `TRUSTLAYER_BIND_LOOPBACK_ONLY` strictness flag, but the
  default `127.0.0.1` bind already covers the common case.

## Follow-ups
- mTLS / OIDC story when a deployment actually demands it.
- Per-agent scoped tokens when the protocol gains a real identity
  model.
- Audit log of authentication failures (currently we just return 401
  and log at debug).
