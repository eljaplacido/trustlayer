# Changelog

All notable, protocol-level and cross-cutting changes to TrustLayer are
recorded here. The format follows [Keep a Changelog]
(https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](./docs/VERSIONING.md). Per-component release tags
(e.g. `python-sdk-v0.2.0`) link back to the entry that introduced the
change.

The authoritative roadmap and per-phase status live in
[`docs/CURRENT_STATUS.md`](./docs/CURRENT_STATUS.md).

---

## [Unreleased]

### Added
- `LICENSE` (Apache-2.0) at the repository root.
- `CONTRIBUTING.md` — schema-change protocol, ADR cadence, per-layer
  test commands, new-SDK checklist.
- `CHANGELOG.md` (this file) and `docs/VERSIONING.md` — SemVer policy
  for the wire format and for each reference implementation.
- `.github/workflows/ci.yml` — matrix CI runs `cargo fmt --check`,
  `cargo clippy -- -D warnings`, `cargo test --features server`, every
  pytest target (SDK + Hermes + MCP), and the TypeScript layers'
  typecheck + tests on every push and PR.
- **ADR-007 — bearer-token auth on guardian + trace store.** Optional
  `TRUSTLAYER_API_TOKEN` env var; when set, every route except
  `/healthz` requires `Authorization: Bearer <token>` (constant-time
  compare via `subtle`). Python + TypeScript SDKs gain env fallback;
  dashboard reads `VITE_TRUSTLAYER_API_TOKEN` at build time.
- **ADR-009 — policy hot-reload via file watch.** `notify`-based
  watcher with 200 ms debounce; `arc_swap::ArcSwap<Policy>` for wait-
  free swap on the hot path; parse failure keeps the live policy in
  place. Opt-out via `TRUSTLAYER_POLICY_RELOAD=false`.
- **Sidecar `/metrics` endpoint (Prometheus text format).** Four
  series: `trustlayer_requests_total{route,status}` (request count
  with matched-template route labels — bounded cardinality),
  `trustlayer_check_total{decision}` (PASS/FAIL/ESCALATE pre-touched
  at zero), `trustlayer_events_ingested_total`, and
  `trustlayer_check_duration_seconds` histogram. Mounted outside the
  auth layer, same as `/healthz`.
- **Ingest rate limit on `POST /v1/events`.** In-house per-second
  token bucket; `TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC` configures it
  (unset = unlimited). 429 with `Retry-After: 1` on overflow; scoped
  only to POST.
- **MCP HTTP/SSE transport** selectable via `TRUSTLAYER_MCP_TRANSPORT`
  (default `stdio`); SSE binds to `TRUSTLAYER_MCP_BIND` (default
  `127.0.0.1:8090`). Unknown values fall back to stdio.
- **Dashboard component tests** (React Testing Library + jsdom) for
  all four panes (Traces, Sessions, Reflections, Policy) covering
  loading / error / empty / loaded states and drill-down clicks.
- **Formal v0.1 protocol spec** under `spec/v0.1/`. Six normative
  documents (wire format, event types, Cynefin domain, policy
  language including ADR-008 payload predicates, HTTP API,
  conformance) plus a versioned index. The spec is the citable
  source of truth; `docs/SCHEMA.md` becomes the implementation
  mirror. ADR-010 records the layout.

### Wire format (MINOR — additive, backwards-compatible)
- **ADR-008 — `MatchSpec` payload predicates.** `MatchSpec` gains an
  optional `payload: map<dotted-path, json>` field. Each key is a
  dotted path into `event.payload`; the predicate matches when the
  resolved value is deep-equal to the JSON literal. Numeric segments
  index arrays. Missing paths never match. `null` literals match
  `null` values only — not missing keys. Existing policies parse
  unchanged.

### Changed
- `core-rs/` clippy + fmt warnings are now denied in CI (Phase-4
  follow-up closed).
- `CynepicGuardian::policy()` now returns `Arc<Policy>` (was `&Policy`)
  because the policy lives behind `ArcSwap` (ADR-009). Internal API;
  no wire impact.
- `core-rs/policies/default.json` — added a
  `block_gpt4_via_payload_predicate` rule as a worked ADR-008 example.

---

## [0.1.0] — 2026-05-22

First end-to-end working stack. Five phases landed in order on the
single canonical wire format. See
[`docs/CURRENT_STATUS.md`](./docs/CURRENT_STATUS.md) for the full
detail; the entries below are protocol-level highlights.

### Wire format
- `AgentTraceEvent` (`docs/SCHEMA.md`) — Pydantic, Zod, and serde
  mirrors all locked together with a cross-language round-trip test.
- Seven `event_type` values, Cynefin domain tagging, metrics envelope.

### Phase 1 — Specifications & scaffolding (2026-05-06)
- Monorepo layout: `core-rs/`, `sdks/`, `skills/`, `obsidian_vault/`,
  `docs/`.
- `docs/ARCHITECTURE.md`, `docs/SCHEMA.md`, `CLAUDE.md`.

### Phase 2 — SDKs (2026-05-07)
- `trustlayer-sdk` (Python, Pydantic + httpx) — `Tracer`, context-
  managed `tool_call`, `instrument_tool` decorator. 15 pytest cases.
- `@trustlayer/sdk` (TypeScript, Zod + fetch) — `Tracer`, `wrapTool`.
  16 vitest cases.
- ADR-001 records the SDK-first wedge.

### Phase 3 — Hermes memory agent (2026-05-10)
- `HermesAgent` — schema-typed ingestion, per-session markdown notes
  in `obsidian_vault/03_Memory_Traces/`, dated reflection notes in
  `obsidian_vault/05_Reflections/`.
- `DeterministicReflector` + `ReflectionEngine` Protocol for future
  LLM swap-in.
- CLI: `python -m hermes.cli ingest <jsonl> [--reflect]`. 18 pytest
  cases. ADR-002.

### Phase 3.5 — Hermes token / memory optimisation (2026-05-13)
- `max_payload_chars`, bounded LRU session cache, JSONL sidecar
  persistence for crash-resumable `reflect()`,
  `SessionSummary.compact_text()` for LLM prompts. 33 Hermes tests.
  ADR-003.

### Phase 4 — Rust core & cynepic-guardian (2026-05-13)
- Rust mirror of `AgentTraceEvent`, CSL policy parser, `cynepic-
  guardian` evaluator (ordered rule walk, Cynefin-aware default
  escalation for `CHAOTIC`), Axum HTTP sidecar `trustlayer-guardian`.
- Python `GuardianClient` (fail-open). 19 Rust + 8 Python guardian
  tests. ADR-004.

### Phase 4.5 — TypeScript guardian client (2026-05-16)
- `@trustlayer/sdk` gains `GuardianClient` + `Tracer.check()` parity
  with the Python SDK. 27 TS tests.

### Phase 4.6 — Code-graph sense-making (2026-05-13)
- `CodeGraphImporter` reads a GitNexus-style JSON graph and emits
  Obsidian notes under `obsidian_vault/06_Code_Graph/`. New `import-
  code-graph` CLI subcommand. 44 Hermes tests. ADR-005.

### Phase 5 — Observe layer (2026-05-17 → 2026-05-22)
- **MCP server** (`mcp-server/`) — Python FastMCP stdio, 5 tools
  wrapping SDK + Guardian + Hermes. 12 pytest cases.
- **Trace-store API** on `trustlayer-guardian` — `POST /v1/events`,
  `GET /v1/events` (filters: `agent_id`, `session_id`, `event_type`,
  `limit`), `GET /v1/sessions`, `GET /v1/sessions/:a/:s`, `GET
  /v1/reflections`, `GET /v1/reflections/:name`. Append-only JSONL
  with replay-on-open, idempotent on `trace_id`, permissive CORS.
- **Dashboard** (`dashboard/`) — React + Vite + TS strict. Four live
  panes (Traces, Sessions, Reflections, Policy). 11 vitest cases on
  the api-client layer.
- Rust totals: 47 tests (31 lib unit + 4 cross-language + 12 HTTP
  integration). ADR-006.

### Tests
At the end of `0.1.0`: **157 tests** across Python SDK (27), Hermes
(44), TypeScript SDK (27), Rust core (47), MCP server (12),
Dashboard (11) — verified locally before each phase commit.

### Known limitations
- Trace-store ingest is **loopback-only**; no auth. Tracked as a
  blocker for any non-local deployment.
- `MatchSpec` predicates only over `event_type`, `tool_name`,
  `agent_id`, `cynefin_domain` — not arbitrary payload fields.
- No MCP HTTP/SSE transport — stdio only.
- Guardian invocation is HTTP-only (~100µs); no pyo3 FFI yet.

[Unreleased]: https://github.com/eljaplacido/trustlayer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/eljaplacido/trustlayer/releases/tag/v0.1.0
