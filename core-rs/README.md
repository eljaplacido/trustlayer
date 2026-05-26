# trustlayer-core (Rust)

Rust implementation of the TrustLayer policy + trace-store plane.
Ships as a library (`trustlayer_core`) and a binary
(`trustlayer-guardian`) that serves the full v0.1 HTTP API: policy
adjudication, append-only event ingest, session reads, Hermes
reflection reads, `/metrics`, and `/healthz`. Apache-2.0.

- **Wire-format conformance:** [v0.1 W1–W7](../spec/v0.1/06-conformance.md)
- **Policy-engine conformance:** [v0.1 P1–P6](../spec/v0.1/06-conformance.md#63-policy-engine-conformance)
- **HTTP-API conformance:** [v0.1 H1–H6](../spec/v0.1/06-conformance.md#64-http-api-conformance)
- **Requires:** Rust stable (currently tested against 1.94)

See the root [README](../README.md) for the full architecture and the
[`spec/v0.1/`](../spec/v0.1/) directory for the citable protocol.

## Build & test

```bash
# Library + binary
cargo build --release --features server --bin trustlayer-guardian

# Full matrix (86 tests across lib unit, cross-language, HTTP, policy-watch)
cargo test --features server

# Lints + format
cargo fmt --check
cargo clippy --features server --all-targets -- -D warnings
```

The `server` feature gates the Axum binary and the HTTP integration
tests. Library-only consumers (downstream Rust crates importing
`trustlayer_core` for its schema or policy engine) can build with
`--no-default-features` and skip the server deps entirely.

## Run the sidecar

```bash
cargo run --release --features server --bin trustlayer-guardian
```

Defaults:

- Binds `127.0.0.1:8089`
- Loads `policies/default.json`
- Appends events to `./events.jsonl`
- Reads reflection notes from `./obsidian_vault/05_Reflections/`
- Auth disabled (loopback only)
- Hot-reloads the policy file on disk changes

Override any of those via env vars (see [Configuration](#configuration)).

## HTTP API

Required v0.1 routes ([spec §5.1](../spec/v0.1/05-http-api.md#51-required-routes)):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/check` | Adjudicate one event. Returns `{decision, rule, reason, policy}`. |
| `POST` | `/v1/events` | Ingest events (single or array). Idempotent on `trace_id`. Optional rate limit. |
| `GET` | `/v1/events` | List events. Filters: `agent_id`, `session_id`, `event_type`, `limit`. |
| `GET` | `/v1/sessions` | Per-`(agent_id, session_id)` summaries. |
| `GET` | `/v1/sessions/{agent_id}/{session_id}` | One session's chronological event list. |
| `GET` | `/healthz` | Liveness probe. Always unauthenticated. |

Optional v0.1 routes:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/reflections` | Hermes reflection notes (`{name, date}` array). |
| `GET` | `/v1/reflections/{name}` | One reflection note. Path-traversal rejected with `400`. |
| `GET` | `/metrics` | Prometheus text exposition. Always unauthenticated. |

Full request / response shapes: [`spec/v0.1/05-http-api.md`](../spec/v0.1/05-http-api.md).

## Policy language (CSL)

Policies are JSON files — a `name` plus an ordered `rules` array.
The guardian walks rules top-to-bottom and returns the first match.

```json
{
  "name": "default",
  "rules": [
    {
      "name": "block_external_llm",
      "match": {
        "event_type": "TOOL_CALL",
        "tool_name":  "external_llm"
      },
      "decision": "FAIL",
      "reason":   "External LLM disabled."
    },
    {
      "name": "block_gpt4_via_payload",
      "match": {
        "event_type": "LLM_CALL",
        "payload":    { "model": "gpt-4" }
      },
      "decision": "FAIL"
    }
  ]
}
```

`MatchSpec` supports `event_type`, `tool_name` (shortcut for
`payload.tool_name`), `agent_id`, `cynefin_domain`, and a `payload`
map of **dotted-path → JSON literal** with deep-equality semantics —
see [spec §4.3](../spec/v0.1/04-policy-language.md#43-payload-predicates)
and [ADR-008](../obsidian_vault/01_Architecture/ADR-008-MatchSpec-Payload-Predicates.md).

The default verdict when no rule matches:

- `cynefin_domain == "CHAOTIC"` → `ESCALATE`
- otherwise → `PASS`

## Hot reload (ADR-009)

The sidecar watches the policy file via `notify` (200 ms debounce).
On any modify/create event it re-reads and parses the file; on
success it atomically swaps in the new policy
(`arc_swap::ArcSwap<Policy>`), on parse failure it logs a warning
and keeps the live policy in place.

```bash
# Edit the policy on disk — no restart needed.
$EDITOR /etc/trustlayer/policy.json
# Sidecar logs: "policy reloaded: name=default rules=4"

# Disable the watcher for ephemeral test sidecars:
TRUSTLAYER_POLICY_RELOAD=false trustlayer-guardian
```

## Auth (ADR-007)

When `TRUSTLAYER_API_TOKEN` is set, every route **except `/healthz`
and `/metrics`** requires `Authorization: Bearer <token>`. The
comparison is constant-time via `subtle::ConstantTimeEq`.

```bash
export TRUSTLAYER_API_TOKEN=$(openssl rand -hex 32)
trustlayer-guardian
```

Wrong / missing token → `401 Unauthorized` with `WWW-Authenticate:
Bearer realm="trustlayer"`.

The Python, TypeScript, and Go SDKs all fall back to the same env
var when no `api_key` is passed, so a single `export` propagates the
secret across the fleet.

## Rate limit

Optional per-second token bucket on `POST /v1/events`:

```bash
export TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC=200
trustlayer-guardian
```

Over-quota requests get `429 Too Many Requests` with `Retry-After: 1`.
Unset or `0` → unlimited (the default). `GET /v1/events` is **not**
rate-limited.

## Metrics

```
trustlayer_check_total{decision="PASS|FAIL|ESCALATE"}    counter
trustlayer_events_ingested_total                         counter
trustlayer_check_duration_seconds                        histogram
trustlayer_requests_total{route, status}                 counter
```

The verdict counter is pre-touched at zero for all three decisions
so dashboards work from a cold start. Route labels use the *matched
router template* (e.g. `/v1/sessions/:agent_id/:session_id`), not
literal URIs, so cardinality stays bounded. Recommended PromQL alerts
and KPIs are in the [root README](../README.md#observability--kpis).

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `TRUSTLAYER_BIND` | `127.0.0.1:8089` | Listen address. |
| `TRUSTLAYER_POLICY` | `./policies/default.json` | Policy file path. |
| `TRUSTLAYER_POLICY_RELOAD` | `true` | `false` disables the file watcher. |
| `TRUSTLAYER_EVENTS_PATH` | `./events.jsonl` | JSONL trace store path. `""` = in-memory only. |
| `TRUSTLAYER_VAULT_PATH` | `./obsidian_vault` | Vault root for `/v1/reflections`. |
| `TRUSTLAYER_API_TOKEN` | _(unset)_ | When set, gates every route except `/healthz` and `/metrics`. |
| `TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC` | _(unset)_ | `POST /v1/events` rate limit. Unset / `0` = unlimited. |
| `RUST_LOG` | `info` | `tracing_subscriber` filter. |

## Layout

```
core-rs/
├── Cargo.toml
├── policies/
│   └── default.json         Example CSL policy
├── src/
│   ├── lib.rs               Public re-exports
│   ├── error.rs             Error / Result
│   ├── schema.rs            AgentTraceEvent + enums (serde mirror)
│   ├── policy.rs            Policy / PolicyRule / MatchSpec + payload predicates
│   ├── guardian.rs          CynepicGuardian (ArcSwap policy) + Verdict
│   ├── policy_watch.rs      notify watcher + reload loop
│   ├── events.rs            EventStore (in-memory + append-only JSONL)
│   ├── reflections.rs       Hermes reflection-note reader (path-traversal guarded)
│   ├── metrics.rs           ServerMetrics + request-tracking middleware
│   ├── rate_limit.rs        Per-second token bucket
│   ├── auth.rs              Bearer-token middleware (constant-time compare)
│   ├── server.rs            Axum router (shared by binary and tests)
│   └── bin/
│       └── guardian.rs      `trustlayer-guardian` binary entry point
└── tests/
    ├── cross_language.rs    Parses fixtures emitted by every SDK
    ├── http_events.rs       HTTP integration tests
    └── policy_watch.rs      Hot-reload integration tests
```

## Library use (no HTTP server)

```toml
[dependencies]
trustlayer-core = { version = "0.1", default-features = false }
```

Downstream consumers get the schema, policy parser, evaluator, and
event store without the Axum / Tokio / Prometheus deps.

```rust
use trustlayer_core::{CynepicGuardian, Policy};

let policy = Policy::from_path("policies/default.json")?;
let guardian = CynepicGuardian::new(policy);
let verdict = guardian.evaluate(&event);
```

## Links

- [Root README](../README.md) — full architecture, deployment, KPI playbook.
- [v0.1 specification](../spec/v0.1/) — the citable protocol.
- ADRs: [004 — Guardian + Policy engine](../obsidian_vault/01_Architecture/ADR-004-Cynepic-Guardian-Policy-Engine.md), [007 — Bearer-token auth](../obsidian_vault/01_Architecture/ADR-007-Auth-Bearer-Token.md), [008 — Payload predicates](../obsidian_vault/01_Architecture/ADR-008-MatchSpec-Payload-Predicates.md), [009 — Policy hot-reload](../obsidian_vault/01_Architecture/ADR-009-Policy-Hot-Reload.md).
- [Contributing](../CONTRIBUTING.md).
