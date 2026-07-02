---
adr: 15
title: Pluggable Trace Store + Postgres Backend
date: 2026-06-30
status: accepted
---

# ADR-015 — Pluggable Trace Store with a Postgres Backend

## Context

Through Phase 6 the trace store was a single concrete type,
`events::EventStore` — an in-memory `Vec<AgentTraceEvent>` mirrored to an
append-only JSONL file. It is zero-dependency, fast, and perfect for local
development and small single-node deployments. It has three ceilings that
block production use at scale:

1. **Single-node only.** The state lives in one process's memory and one
   local file. You cannot run multiple guardian replicas behind a load
   balancer against one shared trace history.
2. **No retention / rotation.** The JSONL file grew without bound; a
   long-running sidecar would eventually exhaust disk and replay-on-open
   would get slow.
3. **No real query surface.** Filtering and session rollups are linear
   scans over the in-memory vector.

The default open-auth posture (`TRUSTLAYER_API_TOKEN` unset) was also a
footgun: a sidecar bound to `0.0.0.0` with no token exposed every trace
and the policy-adjudication endpoint to anyone who could reach the port.

## Decision

### 1. A `TraceStore` trait as the backend seam

Introduce an object-safe async trait (`events::TraceStore`, via
`async-trait`) with the four operations the HTTP routes need:
`append_batch`, `list_events`, `list_sessions`, `get_session`. The router
state holds `Arc<dyn TraceStore>` instead of `Arc<EventStore>`, so the same
routes serve any backend with no handler changes.

`EventStore` keeps its existing **synchronous** inherent methods (its 11
unit tests are untouched) and gains a thin `TraceStore` impl that delegates
to them — local file I/O is sub-100 µs, so the async methods complete
synchronously. Query methods on the trait return `Result` because remote
backends can fail mid-call; the JSONL backend never errors on reads but
conforms to the same contract.

### 2. Postgres backend (`postgres` feature)

A new `pg_store::PostgresStore` implements `TraceStore` over a `sqlx`
connection pool. Design parity with JSONL:

- **Idempotent on `trace_id`** via `INSERT ... ON CONFLICT (trace_id) DO
  NOTHING`; `rows_affected()` gives the same "newly stored" count.
- **Chronological order** via a monotonic `BIGSERIAL seq`.
- **`limit` selects the most-recent N**, returned oldest-first (fetch
  `ORDER BY seq DESC LIMIT n`, then reverse), matching the JSONL tail
  semantics so the dashboard behaves identically on either backend.
- Full event stored as `JSONB`; envelope columns (`agent_id`,
  `session_id`, `ts`, `event_type`) are denormalised for indexed filters.

Implementation choices:

- **Runtime query API** (`sqlx::query`, `QueryBuilder`), not the
  compile-time-checked `query!` macro, so the crate builds with **no live
  database at compile time** and CI needs no `DATABASE_URL`.
- **rustls** TLS so there is no system OpenSSL dependency.
- **Schema created on connect** (idempotent `CREATE TABLE IF NOT EXISTS`);
  `core-rs/migrations/0001_trace_events.sql` documents the same DDL for
  teams that manage schema out-of-band.
- The `postgres` feature is **additive and orthogonal** to `server`. Build
  with `--features server,postgres`. The Docker image ships with both, so
  one image serves JSONL (no DSN) or Postgres (`TRUSTLAYER_DATABASE_URL`
  set). A DSN set against a binary built without the feature is a clear
  startup error, not a silent fallback.

Horizontal scale is now a deployment concern, not a code change: point N
stateless guardian replicas at one Postgres
(`docker compose ... up --scale guardian=3`).

### 3. JSONL retention

`EventStore::with_retention(Some(n))` caps the in-memory log and compacts
the JSONL file (write-tmp-then-rename) once it overruns `n + n/4`, so
steady-state appends stay amortised O(1). Configured by
`TRUSTLAYER_EVENT_RETENTION_MAX`; unset = unbounded (prior behaviour). For
high-volume workloads the Postgres backend is the recommended path —
JSONL retention is best-effort.

### 4. Secure-by-default bind guard

The guardian now **refuses to start** when all of: no `TRUSTLAYER_API_TOKEN`,
a non-loopback `TRUSTLAYER_BIND`, and `TRUSTLAYER_ALLOW_INSECURE` not set
to `true`. Loopback binds stay open for zero-config local dev (with a
warning). This makes "exposed and unauthenticated" an explicit opt-in
rather than the accidental default.

## Consequences

- **No wire-format or API change.** The HTTP contract in `spec/v0.1` is
  unchanged; only the storage implementation behind it is now pluggable.
- The default build and the JSONL behaviour are byte-for-byte unchanged
  when no DSN / retention / token is configured — existing deployments
  keep working.
- New dependencies (`async-trait` always; `sqlx` only under `postgres`).
  `async-trait` is tiny; `sqlx` is gated so the default build stays lean.
- Postgres tests are opt-in (`TRUSTLAYER_TEST_DATABASE_URL`) so the
  default `cargo test` matrix stays hermetic; CI can add a Postgres
  service to exercise them.
- See `docs/SCALING.md` for the operator-facing deployment guide.
