# Changelog

All notable changes to the TrustLayer protocol and reference
implementations are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 8 — EU AI Act compliance depth)

**Slice 8.0 — event-type lockstep (gap G0).** `compliance/schemas/control.schema.json`
enumerated seven event types while `core-rs` `EventType` had nine, so loading
`article-50-v1.yaml` raised `ValidationError` — the Art. 50 control catalog was
dead code. Fixed across the schema, `spec/v0.1/01-wire-format.md` §1.3 and
§2 ("seven" → "nine"), and `docs/SCHEMA.md`, with payload contracts added for
`DISCLOSURE_SHOWN` and `CONTENT_MARKED`.
- Regression tests: `test_event_type_lockstep.py` parses the Rust enum as the
  source of truth and asserts the spec prose and compliance schema agree;
  `test_control_catalogs.py` loads **every** catalog in `compliance/controls/`.
- `spec/v0.1/fixtures/` is now read by all five implementations (Rust core plus
  the Python, TypeScript and Go SDKs), each asserting strict-envelope parse,
  field preservation, fixed-point round-trip, and rejection of an unknown
  field. A fixture read only by the language that produced it proves nothing
  about interoperability — that omission is what produced G0.

**Slice 8.1 — Art. 12 evidence integrity (ADR-017).**
- **Tamper-evident hash chain**, scoped per `agent_id`, over a canonical
  event serialisation. `Seq` and `EventHash` newtypes make it a type error to
  put a chain hash where a content hash belongs. `recorded_at` is the store's
  clock, never the client's `timestamp`.
- **Signed checkpoints.** Ed25519 commitments to a chain head, written to
  `events.checkpoints.jsonl` every `TRUSTLAYER_INTEGRITY_CHECKPOINT_EVERY`
  appends or `…_INTERVAL_SECS` seconds, plus one on graceful shutdown.
  `TRUSTLAYER_SIGNING_KEY` takes a hex seed or a `chmod 600` file. Key
  *generation* is deliberately not implemented — see `docs/SCALING.md`.
  Unsigned checkpoints are still emitted; archived off-box they still pin the
  prefix.
- **New routes** (additive, MINOR per spec §1.7; normative in
  `spec/v0.1/05-http-api.md` §5.12): `GET /v1/events/chained`,
  `GET /v1/integrity/verify`, `GET /v1/integrity/checkpoints`, and an
  `after_seq` cursor on `GET /v1/events`. A backend with no chain answers
  `501`, not `500` — it is healthy, it just cannot attest.
- **New metrics**: `trustlayer_retention_live_events`,
  `trustlayer_retention_archived_total`,
  `trustlayer_retention_floor_blocked_total`,
  `trustlayer_integrity_checkpoints_total`,
  `trustlayer_integrity_chains_total`.

### Changed (Phase 8)
- **`TRUSTLAYER_EVENT_RETENTION_MAX` no longer deletes.** It was a hard cap
  that evicted the oldest events on overflow, which could destroy logs Art. 12
  requires be kept for six months. It is now a *soft target*: overflow is
  appended to `events.archive.jsonl` and the live log compacted. Strictly
  safer, and no configuration change is required.
- **New retention floor.** `TRUSTLAYER_RETENTION_MIN_DAYS` (default `180`;
  set `730` for biometric / law-enforcement systems) defines a minimum age
  before an event may leave the live log. **It outranks the count target**: if
  honouring the target would evict a younger event, the store keeps it, lets
  the live log grow, and increments
  `trustlayer_retention_floor_blocked_total`. Destroying evidence is a
  conformity failure; an oversized log is an operations problem. `0` disables
  the floor and logs a warning.
- `GET /v1/events` accepts `after_seq`. Its response shape is **unchanged** —
  chain metadata is served from `/v1/events/chained` so no route returns two
  different bodies.

### Deferred (Phase 8)
- **Postgres integrity parity.** The `postgres` backend answers the integrity
  routes with `501` rather than a chain it does not maintain. Shipping
  untested SQL behind an Art. 12 tamper-evidence claim would be worse than
  saying plainly that it is not implemented; CI has no database.
- Merkle inclusion proofs (chain replay suffices at current volumes) and
  runtime trust-envelope enforcement — both Phase 9.

### Added (Phase 6 — Production hardening, ADR-015)
- **Pluggable trace store.** New object-safe `TraceStore` trait; the HTTP
  sidecar now holds `Arc<dyn TraceStore>` so the same routes serve any
  backend. No wire-format or HTTP-API change.
- **Postgres backend** (`postgres` build feature). Durable, horizontally
  scalable: run N stateless guardian replicas against one database
  (`docker compose -f docker-compose.yml -f docker-compose.postgres.yml up
  --scale guardian=3`). Schema auto-created on connect;
  `core-rs/migrations/0001_trace_events.sql` documents the DDL. Selected at
  runtime with `TRUSTLAYER_DATABASE_URL`. Verified end-to-end against a live
  Postgres (append/dedup/filter/limit/sessions/get-session).
- **JSONL retention.** `TRUSTLAYER_EVENT_RETENTION_MAX` caps the log and
  compacts the file on overflow (amortised O(1) appends). Unset = unbounded
  (unchanged default).
- **Secure-by-default bind guard.** The guardian refuses to start on a
  non-loopback address without `TRUSTLAYER_API_TOKEN`, unless
  `TRUSTLAYER_ALLOW_INSECURE=true`. Loopback dev stays zero-config.
- `docs/SCALING.md` — operator guide for backend choice, replicas, retention,
  and the security checklist.

### Changed
- Docker image builds with `--features server,postgres` by default (one image
  serves either backend); override with `--build-arg FEATURES=server`.
- `.gitignore` now covers the default `events.jsonl` runtime log.

### Tests
- Rust: **88** default (+2 JSONL retention) and **+3** opt-in Postgres
  integration tests (`TRUSTLAYER_TEST_DATABASE_URL`), all green. `cargo fmt`
  + `clippy -D warnings` clean for both `server` and `server,postgres`.
- Dashboard visually verified end-to-end against the live API (Playwright):
  all four panes render real data, zero console errors.

## [0.1.0] — 2026-05-30

### Added (Phase 1 — Specifications & Scaffolding)
- Monorepo structure (`core-rs`, `sdks`, `skills`, `obsidian_vault`).
- Canonical trace schema (`docs/SCHEMA.md`) with `AgentTraceEvent`
  envelope and seven event types.
- Architectural blueprint (`docs/ARCHITECTURE.md`).
- Agentic guidelines (`CLAUDE.md`).

### Added (Phase 2 — Developer Wedge)
- Python SDK (`trustlayer-sdk`): Pydantic v2 schema, httpx client,
  `Tracer` with `tool_call` context manager and `instrument_tool`
  decorator. 27 pytest cases.
- TypeScript SDK (`@trustlayer/sdk`): Zod schema, fetch client,
  `Tracer`, `wrapTool` helper. 27 vitest cases.
- Both SDKs swallow transport failures so instrumentation cannot break
  the host agent.
- ADR-001 — SDK Wedge.

### Added (Phase 3 — Hermes Memory Agent)
- Schema-typed ingestion accepting `AgentTraceEvent`, `dict`, and
  JSON-string inputs.
- Per-session Markdown notes in `obsidian_vault/03_Memory_Traces/`.
- `DeterministicReflector` with structural summaries.
- `ReflectionEngine` Protocol for future LLM-backed reflection.
- CLI: `python -m hermes.cli --vault <vault> ingest <jsonl> [--reflect]`.
- 18 pytest cases. ADR-002.

### Added (Phase 3.5 — Token / Memory Optimisation)
- Payload truncation (`max_payload_chars`, default 2 000).
- JSONL sidecar persistence (`<vault>/.hermes_state/`).
- Bounded LRU cache (`max_cached_sessions`, default 256).
- `SessionSummary.compact_text()` for LLM-friendly prompts.
- 15 new pytest cases (33 Hermes tests total). ADR-003.

### Added (Phase 4 — Rust Core)
- Rust serde mirror of `AgentTraceEvent` with `deny_unknown_fields`.
- CSL policy parser with named rules and `MatchSpec` selectors.
- `cynepic-guardian` evaluator: ordered rule walk, first-match-wins,
  Cynefin-aware CHAOTIC default escalation.
- Axum HTTP sidecar (`trustlayer-guardian`):
  `POST /v1/check`, `GET /healthz`, graceful shutdown.
- Python `GuardianClient` with fail-open default. 8 new pytest cases
  (23 Python tests total).
- Default policy (`core-rs/policies/default.json`).
- 19 Rust tests (15 unit + 4 cross-language). ADR-004.

### Added (Phase 4.5 — SDK Guardian Parity)
- TypeScript `GuardianClient` + `Tracer.check()` (11 new vitest cases,
  27 TypeScript tests total).
- Python `Tracer.check()` helper combining guardian call + `POLICY_CHECK`
  event. 4 new pytest cases (27 Python tests total).

### Added (Phase 4.6 — Code-Graph Sense-Making)
- `skills/hermes/code_graph.py` — `CodeGraphImporter` reads generic
  JSON graph and emits Obsidian notes into `06_Code_Graph/`.
- CLI: `python -m hermes.cli import-code-graph --gitnexus-root <path>`.
- 11 new pytest cases (44 Hermes tests total). ADR-005.

### Added (Phase 5 — Dashboard & MCP Server)
- Trace-store API on `trustlayer-guardian`:
  `POST /v1/events`, `GET /v1/events` (filtered),
  `GET /v1/sessions`, `GET /v1/sessions/:agent/:session`,
  `GET /v1/reflections`, `GET /v1/reflections/:name`.
- `EventStore`: append-only JSONL, idempotent on `trace_id`,
  replay on open, permissive CORS.
- Dashboard (React + Vite, 4 panes): Traces, Sessions, Reflections,
  Policy. Each pane has loading/error/empty states.
- MCP server (Python, FastMCP stdio): 5 tools wrapping SDK + Guardian +
  Hermes. Transport-free handlers, 12 pytest cases.
- 47 Rust tests (31 lib unit + 4 cross-language + 12 HTTP integration).
  ADR-006.

### Added (Production Readiness)
- `LICENSE` file (Apache 2.0).
- `CONTRIBUTING.md` with development guide, code style, and PR checklist.
- `CHANGELOG.md` (this file).
- CI/CD workflow (GitHub Actions): test, lint, typecheck, and build
  across all layers (Rust, Python, TypeScript, Go, Hermes, MCP, Dashboard).
- `docs/VERSIONING.md` — SemVer policy for wire format and per-package.
- `docs/RELEASE.md` — release process and checklist.

### Added (Phase 6 Slice 2 — Protocol Hardening)
- ADR-007 — bearer-token auth (`core-rs/src/auth.rs`, `TRUSTLAYER_API_TOKEN`).
- ADR-008 — `MatchSpec` payload predicates with dotted-path resolution
  (`core-rs/src/policy.rs::resolve_path`).
- ADR-009 — policy hot-reload via `notify` file watcher and `ArcSwap`
  (`core-rs/src/policy_watch.rs`).

### Added (Phase 6 Slice 3 — Surface Completeness)
- Prometheus `/metrics` endpoint (`core-rs/src/metrics.rs`).
- Ingest rate limiter on `POST /v1/events` (`core-rs/src/rate_limit.rs`).
- MCP server SSE transport alongside stdio.
- Dashboard component tests (React Testing Library, 19 new cases).

### Added (Phase 6 Slice 4a — Formal Spec)
- `spec/v0.1/` — six RFC-2119 normative documents (wire format, event
  types, Cynefin, policy language, HTTP API, conformance).
- `spec/v0.1/fixtures/` — conformant event fixtures.
- ADR-010 — formal spec layout.

### Added (Phase 6 Slice 4b — Go SDK)
- `sdks/go/trustlayer/` — Go SDK mirroring the Python/TS contract.
  31 Go tests (schema + client + guardian + tracer).
- Conformance fixture: `spec/v0.1/fixtures/event-canonical-go.json`.
- ADR-011 — Go SDK design.

### Added (Phase 6 Slice 4c — OpenTelemetry)
- `trustlayer.otel.OTelExporter` — bridges `AgentTraceEvent` to OTel spans.
  16 new pytest cases.
- ADR-012 — OpenTelemetry integration.

### Added (Phase 6 Slice 4d — LLM-Backed Reflection)
- `skills/hermes/llm_reflector.py` — `LLMReflector` calls Ollama (or any
  OpenAI-compatible endpoint) to produce narrative reflections from
  session summaries. Best-effort: falls back to deterministic when the
  LLM is down. 12 new pytest cases.
- ADR-013 — LLM-backed reflection.

### Added (Phase 6 Slice 4e — pyo3 FFI)
- `core-rs/src/ffi.rs` — Python native extension via `pyo3` (`python`
  feature). Exposes `trustlayer_native.TrustLayerGuardian` with JSON-
  string I/O for in-process policy evaluation without HTTP overhead.
  Buildable with `maturin develop --features python`.
- ADR-014 — pyo3 FFI embedding.

### Added (Phase 6 Slice 4f — Deployment)
- `Dockerfile` — multi-stage build for the guardian sidecar.
- `docker/Dockerfile.dashboard` — nginx-served SPA.
- `docker/Dockerfile.hermes` — Hermes reflection loop.
- `docker-compose.yml` — self-hosted quickstart with guardian, dashboard,
  and optional Hermes profile.

### Fixed (Release Hardening — 2026-06-22)
- Dashboard `ReflectionsPane`: removed `aria-label` on date buttons so
  accessible name matches visible text; component tests now pass cleanly.
- Hermes CLI: fixed `_build_reflector` return type (`object` →
  `ReflectionEngine`) for mypy compliance.
- Hermes package: added `py.typed` marker so downstream packages (MCP
  server) type-check cleanly.
- All lint/type/fmt gates verified green across the full matrix.

[0.1.0]: https://github.com/trustlayer/trustlayer/releases/tag/v0.1.0
