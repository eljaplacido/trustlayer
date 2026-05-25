# Current Status

**Phase:** Phase 6 — Slice 4a closed (formal v0.1 spec under `spec/v0.1/`)
**Overall Status:** GREEN

## 📋 Roadmap & Task List

### Phase 1: Specifications & Scaffolding (Complete)
- [x] Create Monorepo Structure (`core-rs`, `sdks`, `skills`, `obsidian_vault`)
- [x] Create Agentic Guidelines (`CLAUDE.md`)
- [x] Define Architectural Blueprint (`docs/ARCHITECTURE.md`)
- [x] Define Trace Schema (`docs/SCHEMA.md`)
- [x] Initialize Python SDK base structure (`sdks/python/pyproject.toml`)
- [x] Initialize TypeScript SDK base structure (`sdks/typescript/package.json`)

### Phase 2: The Developer Wedge (SDKs) (Complete)
- [x] Implement `trustlayer-python` SDK — Pydantic schema, httpx client, Tracer with context-managed `tool_call`, `instrument_tool` decorator
- [x] Implement `trustlayer-typescript` SDK — Zod schema, fetch client, Tracer, `wrapTool` helper
- [x] Tests — 15 pytest cases (passing), 16 vitest cases (passing); both SDKs swallow transport failures so instrumentation can never break the host agent
- [x] Examples — `sdks/python/examples/langchain_style_agent.py`, `sdks/typescript/examples/agent.ts` (both runnable; print events to stdout via mock transport)

### Phase 3: The Hermes Memory Agent (Complete)
- [x] Parse JSON traces — `HermesAgent.ingest()` accepts `AgentTraceEvent`, `dict`, or JSON-string inputs and reuses `trustlayer.schema` for validation.
- [x] Map traces to markdown nodes — one note per `(agent_id, session_id)` written to `obsidian_vault/03_Memory_Traces/<agent>/<session>.md` with YAML frontmatter and a chronological timeline.
- [x] Recursive reflection — `DeterministicReflector` produces structural summaries (tool counts, policy failures, latency totals); `ReflectionEngine` Protocol leaves room for an LLM-backed reflector. Output lands in `obsidian_vault/05_Reflections/reflection-<date>.md`.
- [x] CLI — `python -m hermes.cli --vault <vault> ingest <jsonl> [--reflect]`.
- [x] Tests — 18/18 pytest cases covering ingest idempotency, multi-format input coercion, multi-session separation, reflection aggregation, and CLI exit codes.

### Phase 3.5: Hermes Token / Memory Optimisation (Complete)
- [x] Payload truncation (`max_payload_chars`, default 2 000) — recursive, with `<...truncated N chars>` marker.
- [x] JSONL sidecar persistence at `<vault>/.hermes_state/` — append-only, deduped on `trace_id`, used to rehydrate evicted sessions during `reflect()`.
- [x] Bounded LRU cache (`max_cached_sessions`, default 256) — markdown is flushed before eviction.
- [x] `SessionSummary.compact_text(max_chars=600)` — token-lean one-line summary for LLM reflection prompts.
- [x] 33/33 Hermes tests passing (15 new for the optimisations).
- [x] ADR-003 recorded at `obsidian_vault/01_Architecture/ADR-003-Hermes-Token-Memory-Model.md`.

### Phase 4: Rust Core (Performance & Policy) (Complete)
- [x] Rust mirror of `AgentTraceEvent` (`core-rs/src/schema.rs`) with `deny_unknown_fields` and cross-language test against Pydantic-emitted JSON.
- [x] CSL/Policy parser in `core-rs/src/policy.rs` — JSON document with named rules, `MatchSpec` over `event_type` / `tool_name` / `agent_id` / `cynefin_domain`.
- [x] `cynepic-guardian` evaluator (`core-rs/src/guardian.rs`) — ordered rule walk, first match wins, Cynefin-aware default escalation for `CHAOTIC` events.
- [x] HTTP sidecar — Axum binary `trustlayer-guardian`, `POST /v1/check`, `GET /healthz`, graceful shutdown.
- [x] Python `GuardianClient` + `Verdict` in `sdks/python/src/trustlayer/guardian.py`, fail-open default.
- [x] Default policy at `core-rs/policies/default.json`.
- [x] Tests — **19/19 Rust** (15 unit + 4 cross-language), **8 new Python guardian tests** (23 total in Python SDK).
- [x] End-to-end smoke: Python SDK → live Rust server returning correct FAIL/ESCALATE/PASS across four scenarios.
- [x] ADR-004 recorded at `obsidian_vault/01_Architecture/ADR-004-Cynepic-Guardian-Policy-Engine.md`.
- [x] (Follow-up 4.5) TypeScript SDK guardian client + `Tracer.check()` parity (11 new vitest cases, 27/27 total).
- [x] (Follow-up 4.5) `Tracer.check()` helper combining guardian call + `POLICY_CHECK` event.
- [ ] (Follow-up) `MatchSpec` predicates on arbitrary payload fields.
- [ ] (Follow-up) `cargo clippy` + `cargo fmt` enforcement in CI (`rustup component add clippy rustfmt`).

### Phase 4.6: Code-Graph Sense-Making (Complete)
- [x] ADR-005 records the decision to consume GitNexus (https://github.com/abhigyanpatwari/GitNexus) as the static code-graph indexer and visualization engine rather than rebuild it inside Hermes.
- [x] `skills/hermes/code_graph.py` — `CodeGraphImporter` reads a generic JSON graph (`graph.json` or `nodes.json` + `edges.json`) and emits one Obsidian note per node into `obsidian_vault/06_Code_Graph/<language>/<safe_id>.md`, with `[[wikilink]]` sections for Calls / Imports / Inherits / Contains and their inverses. Decoupled from GitNexus's internal storage so upstream format changes can't break us.
- [x] CLI — `python -m hermes.cli --vault <vault> import-code-graph [--gitnexus-root <path>]` added as a third subcommand.
- [x] Tests — 11 new pytest cases in `test_code_graph.py`. 44/44 Hermes tests pass (33 prior + 11 new).
- [x] `.gitignore` — `.gitnexus/` added.
- [ ] (User action) Register the GitNexus MCP server in `.claude/settings.json` — blocked by auto-classifier as agent-config self-modification.
- [ ] (User action) `npm install -g gitnexus@latest` with `GITNEXUS_SKIP_OPTIONAL_GRAMMARS=1` — blocked by auto-classifier as third-party global install.

### Phase 5: Dashboard & MCP Server
- [x] TrustLayer Dashboard — `dashboard/` Vite + React + TS strict. **All four panes are live:** Traces (`GET /v1/events`), Sessions (`GET /v1/sessions` + drill-down), Reflections (`GET /v1/reflections` + markdown view), Policy (`GET /v1/events?event_type=POLICY_CHECK`, color-coded verdicts). Each pane has consistent loading / error / empty states.
- [x] TrustLayer MCP Server — `mcp-server/` Python package using FastMCP over stdio. Five tools wrap the Python SDK + Guardian + Hermes (`trustlayer_emit_event`, `trustlayer_guardian_check`, `trustlayer_hermes_ingest`, `trustlayer_hermes_get_session`, `trustlayer_hermes_reflect`). Pure handlers in `tools.py`, transport-free; 12/12 pytest cases.
- [x] Trace-store API — `trustlayer-guardian` binary serves `POST /v1/events`, `GET /v1/events` (filters: `agent_id`, `session_id`, `event_type`, `limit`), `GET /v1/sessions`, `GET /v1/sessions/:agent/:session`, `GET /v1/reflections`, `GET /v1/reflections/:name`. `EventStore` in `core-rs/src/events.rs` (append-only JSONL, idempotent on `trace_id`, replay on open). `core-rs/src/reflections.rs` lists/reads Hermes reflection notes from `TRUSTLAYER_VAULT_PATH` with a path-traversal guard. Router extracted to `core-rs/src/server.rs`. Permissive CORS. 47 Rust tests (31 lib unit + 4 cross-language + 12 HTTP integration).
- [x] (Follow-up) Wire Sessions pane to `GET /v1/sessions` (shipped 2026-05-19).
- [x] (Follow-up) Reflections pane goes through Hermes output — sidecar serves the vault's `05_Reflections/` notes; generation stays Hermes's job (shipped 2026-05-22).
- [ ] (Follow-up) Auth/token gating on ingest routes (loopback-only for v0).
- [ ] (User action) Register `trustlayer-mcp` in `.claude/settings.json` — blocked by auto-classifier on agent-config self-modification.
- [x] (Follow-up 5.1) Dashboard test parity — `dashboard/tests/api.test.ts`, 11 vitest cases against a stubbed `fetch` covering every `api.ts` wrapper (shipped 2026-05-23).

### Phase 6: Open-Protocol Scaffolding (In Progress)
The audit slice that takes TrustLayer from "shipped prototype" to "credible open standard." Repo-hygiene + governance first, then the harder protocol-hardening work in later slices.

- [x] **Slice 1 — Repo hygiene + CI** (shipped 2026-05-24):
  - `LICENSE` (Apache-2.0) at repo root, satisfying the per-package declarations.
  - `CONTRIBUTING.md` — schema-change protocol, ADR cadence, new-SDK checklist, per-layer test commands.
  - `CHANGELOG.md` (Keep-a-Changelog) + `docs/VERSIONING.md` (SemVer policy for the wire format and per-package).
  - `.github/workflows/ci.yml` — matrix runs `cargo fmt --check`, `cargo clippy --features server --all-targets -- -D warnings`, `cargo test --features server`, every pytest target on Python 3.11 + 3.12, and the TS layers' typecheck + test (+ dashboard build) on Node 20 + 22, on every push and PR.
  - Closes the Phase-4 clippy/fmt follow-up; fixed three `map_or` → `is_none_or` lints in `core-rs/src/events.rs` and reformatted six pre-existing fmt-dirty files so the new gate starts green.
  - Verified the full matrix locally before committing — **168 tests** green (Rust 47, Python SDK 27, Hermes 44, MCP 12, TS SDK 27, Dashboard 11).
- [x] **Slice 2 — Protocol hardening** (shipped 2026-05-24):
  - **ADR-007 — bearer-token auth.** Optional `TRUSTLAYER_API_TOKEN`; when set, every route except `/healthz` requires `Authorization: Bearer ...`; constant-time compare via `subtle`; `WWW-Authenticate: Bearer realm="trustlayer"` challenge on 401. Python + TS SDKs gain env fallback so MCP server and dashboard get the behaviour for free. Dashboard reads `VITE_TRUSTLAYER_API_TOKEN` at build time.
  - **ADR-008 — `MatchSpec` payload predicates (dotted-path equality).** New `payload: map<dotted-path, json>` field on `MatchSpec`; AND across keys; missing-path = no match; null literal matches null value only, not absent; numeric segments index arrays; no operators / no JSONPath. `core-rs/src/policy.rs::resolve_path` is the path resolver. Default policy gains a `block_gpt4_via_payload_predicate` rule. Wire-format MINOR (additive, optional).
  - **ADR-009 — policy hot-reload via file watch.** `notify`-based `RecommendedWatcher` plus 200 ms debounce; `arc_swap::ArcSwap<Policy>` inside `CynepicGuardian` for wait-free swap on the `/v1/check` hot path; parse failure logs `warn!` and keeps the live policy. Opt-out via `TRUSTLAYER_POLICY_RELOAD=false`. Watcher armed synchronously before `spawn_watcher` returns so the first post-spawn write is guaranteed to be observed.
  - Test totals after Slice 2: **210** (Rust 74, Python SDK 33, Hermes 44, MCP 12, TS SDK 33, Dashboard 14). Rust gained 27 (1 cross-lang + 7 auth HTTP + 16 policy unit + 3 policy-watch integration). Python SDK gained 6 (auth env fallback in both clients). TS SDK gained 6 (auth env fallback). Dashboard gained 3 (auth header propagation). Full local matrix verified before each topic and at slice close.
- [x] **Slice 3 — Surface completeness** (shipped 2026-05-25):
  - **`/metrics` Prometheus endpoint.** New `core-rs/src/metrics.rs` — `ServerMetrics` owns four time series: `trustlayer_requests_total{route, status}` (HTTP request count; labels use matched router templates so cardinality is bounded), `trustlayer_check_total{decision}` (PASS/FAIL/ESCALATE pre-touched at zero), `trustlayer_events_ingested_total`, and `trustlayer_check_duration_seconds` (latency histogram, default buckets). `track_requests` middleware on every route. `/metrics` is mounted outside the auth layer (same posture as `/healthz`).
  - **Ingest rate limit on `POST /v1/events`.** New `core-rs/src/rate_limit.rs` — in-house per-second token bucket (~50 lines of atomics, no extra crate dep). `TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC` configures it; unset = unlimited. Returns `429 Too Many Requests` with `Retry-After: 1` when exceeded; scoped only to POST (GET /v1/events remains unaffected).
  - **MCP HTTP/SSE transport** alongside stdio. New `resolve_transport()` helper maps env to a `TransportConfig` dataclass; `TRUSTLAYER_MCP_TRANSPORT={stdio,sse}` selects; SSE binds to `TRUSTLAYER_MCP_BIND` (default `127.0.0.1:8090`). Unknown values warn-log and fall back to stdio. Closes the SSE follow-up from ADR-006.
  - **Dashboard component tests** with React Testing Library. Vitest jsdom env per-file; `@testing-library/jest-dom/vitest` matchers via setup file. 19 new tests across the four panes (Traces, Sessions, Reflections, Policy) covering loading/error/empty/loaded states and the click-to-drill-down interactions.
  - Test totals after Slice 3: **244** (Rust 85, Python SDK 33, Hermes 44, MCP 21, TS SDK 33, Dashboard 33). Rust +11 (8 HTTP integration on /metrics + rate-limit, 3 rate_limit unit). MCP +9 (transport resolver). Dashboard +19 (component tests).
- [ ] **Slice 4 — New phases (each gets its own ADR):**
  - [x] **Slice 4a — Formal v0.1 spec under `spec/v0.1/`** (shipped 2026-05-25). ADR-010 captures the layout: versioned directories, RFC 2119 keywords, normative/informative section markers, spec authoritative vs `docs/SCHEMA.md` as the implementation mirror. Six normative documents (wire-format, event-types, cynefin, policy-language, http-api, conformance) plus a spec index and a v0.1 frontmatter README. Cross-linked from `README.md`, `docs/SCHEMA.md`, and `docs/VERSIONING.md`.
  - [ ] Distributed event store (ADR + impl).
  - [ ] `pyo3` FFI embedding of the Rust guardian (ADR + impl).
  - [ ] Go SDK (ADR + impl mirroring Python/TS).
  - [ ] OpenTelemetry exporter (ADR + impl).
  - [ ] LLM-backed reflector in Hermes (ADR + impl).

## 📝 Recent Updates
- **2026-05-25** (latest): Phase 6 Slice 4a landed — formal v0.1 spec. New top-level `spec/` tree with a frozen `v0.1/` directory holding six normative documents and a README index. ADR-010 records the layout decision. `README.md`, `docs/SCHEMA.md`, and `docs/VERSIONING.md` now point at the spec as the citable source of truth and demote themselves to "implementation mirror" status for the same wire format. No code change — **244 tests** still green; the spec freezes the contract every existing test already enforces.
- **2026-05-25**: Phase 6 Slice 3 closed — surface completeness. Three commits: `bc8bf27` (metrics + ingest rate-limit on the sidecar), `01584bc` (MCP SSE transport alongside stdio), and the dashboard component tests in this push. New Rust modules: `core-rs/src/metrics.rs`, `core-rs/src/rate_limit.rs`. New MCP unit-tested surface: `resolve_transport()`. New dashboard testing surface: `vitest.config.ts` + `tests/setup.ts` + 4 component test files. **244 tests** total across the matrix.
- **2026-05-24**: Phase 6 Slice 2 landed — protocol hardening. Three ADRs (007 auth, 008 payload predicates, 009 hot-reload) and matching implementations. New files: `core-rs/src/auth.rs`, `core-rs/src/policy_watch.rs`, `core-rs/tests/policy_watch.rs`, `sdks/typescript/src/auth.ts`. Cargo deps `subtle`, `arc-swap`, `notify` added under the `server` feature (arc-swap is unconditional, it's <1 KB). Wire-format MINOR bump implied by ADR-008 (`payload` field added to `MatchSpec`); existing policies keep parsing unchanged. **210 tests** green across the matrix.
- **2026-05-24**: Phase 6 Slice 1 landed — open-protocol scaffolding. `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/VERSIONING.md`, `.github/workflows/ci.yml` (matrix CI across rust/python/typescript). Phase-4 follow-up closed: `cargo fmt --check` and `cargo clippy --features server -- -D warnings` are now CI gates; three `map_or` → `is_none_or` clippy fixes in `core-rs/src/events.rs` plus a round of `cargo fmt` over six pre-existing fmt-dirty files. Full matrix verified locally before committing: **168 tests** green across all six surfaces.
- **2026-05-23**: Polish batch on Phase 5 — docs/manifests reflect shipped reality (`README.md` roadmap rows, `docs/ARCHITECTURE.md` four-layer story, `docs/SCHEMA.md` trace-store HTTP contract, Guardian/Hermes/MCP manifests bumped). Dashboard tests landed — vitest wired into `dashboard/`, 11 cases against `api.ts` cover URL construction, filter encoding, path-segment escaping, and HTTP-status propagation. Closes the only "no in-language tests for the dashboard" gap.
- **2026-05-22**: Phase 5 dashboard complete — Reflections + Policy panes wired, all four panes now live. Rust sidecar gained `core-rs/src/reflections.rs` (lists/reads Hermes reflection notes from `TRUSTLAYER_VAULT_PATH` with an `is_safe_name` path-traversal guard) plus `GET /v1/reflections` + `GET /v1/reflections/:name` routes, and an `event_type` filter on `GET /v1/events`. Reflections pane lists dates and renders the raw markdown; Policy pane shows recent `POLICY_CHECK` events with colour-coded PASS/FAIL/ESCALATE verdicts. Rust tests +14 (now **47**: 31 lib unit + 4 cross-language + 12 HTTP integration). Combined curl smoke verified all four dashboard endpoints serve correct data. Note: dashboard verified at the HTTP-contract level — no in-browser visual check (no browser tooling in this environment). 157 tests total across all layers.
- **2026-05-19**: Dashboard Sessions pane shipped. New `SessionsPane.tsx` polls `GET /v1/sessions` and renders a summary table; clicking a row toggles an inline timeline fetched from `GET /v1/sessions/:agent/:session`. Same loading / error / empty pattern as the Traces pane. Two new typed wrappers in `api.ts` (`fetchSessions`, `fetchSession`) share a private `getJson<T>` helper so the URL-construction logic stays in one place. Dashboard typecheck + build still green.
- **2026-05-18**: Phase 5 — trace-store API shipped on the Rust sidecar; dashboard Traces pane wired. New `EventStore` (in-memory + append-only JSONL, idempotent on `trace_id`, replay on open) and four routes on `trustlayer-guardian`: `POST /v1/events`, `GET /v1/events`, `GET /v1/sessions`, `GET /v1/sessions/:agent/:session`. Router pulled into `core-rs/src/server.rs` so the binary and integration tests share one source of truth. Permissive CORS via `tower-http`. Dashboard polls `GET /v1/events?limit=50` every 5 s with loading / error / empty states. Live curl smoke verified the full POST → GET round-trip plus CORS preflight. Rust tests: +8 unit + 6 HTTP integration; **33 Rust tests green** (was 19). All 4 layers stay green — 143 tests total. ADR-006 marked resolved on the trace-store decision.
- **2026-05-17**: Phase 5 — MCP server shipped, dashboard scaffolded. New top-level `mcp-server/` (Python, FastMCP stdio, 5 tools wrapping SDK + Guardian + Hermes, 12/12 pytest green) and `dashboard/` (Vite + React + TS strict, four placeholder panes, typecheck + build green). Handlers are transport-free in `tools.py` so they unit-test directly. ADR-006 captures the layout decision, the Python-for-MCP rationale, the stdio-for-v1 choice, and the explicitly deferred trace-store decision for the dashboard.
- **2026-05-16**: Phase 4.5 closed. Python `Tracer.check()` shipped (commit 3cccc6e, 4 new pytest cases) and TypeScript SDK gained `GuardianClient` + `Tracer.check()` parity (11 new vitest cases). All four layers green: Python 27/27, Hermes 44/44, Rust 19/19, TypeScript 27/27 — 117 tests total.
- **2026-05-13** (latest): Phase 4.6 — code-graph sense-making landed. New `skills/hermes/code_graph.py` with `CodeGraphImporter` (Pydantic v2 `CodeNode`/`CodeEdge`, generic JSON input), new `import-code-graph` CLI subcommand, output in a new `obsidian_vault/06_Code_Graph/` surface so the static code graph and runtime memory traces share one navigable vault. 11 new pytest cases, 44/44 total green. ADR-005 captures the design and the PolyForm Noncommercial licensing caveat on GitNexus. Two follow-up actions are user-gated (auto-classifier blocked agent-config self-modification and the global npm install).
- **2026-05-13** (later): Phase 4 — cynepic-guardian shipped. Rust core lib (schema mirror, CSL policy parser, ordered evaluator with Cynefin-aware default), Axum HTTP sidecar binary, Python `GuardianClient` (fail-open by default), 19/19 Rust tests + 8 new Python tests, live end-to-end smoke across FAIL/ESCALATE/PASS scenarios. ADR-004 captures the design.
- **2026-05-13**: Phase 3.5 — Hermes token/memory optimisation. Four bounded, opt-out-able knobs on `HermesAgent` (`max_payload_chars`, `max_cached_sessions`, `persist_events`, `state_path`); crash-resumable `reflect()`; LLM-friendly `SessionSummary.compact_text()`. 33/33 Hermes pytest cases passing. ADR-003 records the model. Also: `docs/ARCHITECTURE.md` rewritten with the actual three-layer data flow, `docs/SCHEMA.md` expanded to document every payload type, root `README.md` rewritten with concrete per-layer quickstarts, `CLAUDE.md` aligned with shipped phase status.
- **2026-05-10**: Phase 3 Hermes landed. `skills/hermes/` is now a real package: schema-typed ingestion, idempotent in-memory cache, per-session markdown notes, structural recursive reflection with a `ReflectionEngine` Protocol for future LLM swap-in, and a CLI. 18/18 pytest cases pass. Smoke run produced live notes in `obsidian_vault/03_Memory_Traces/` and `obsidian_vault/05_Reflections/`. Design recorded at [`obsidian_vault/01_Architecture/ADR-002-Hermes-Memory-Agent.md`](../obsidian_vault/01_Architecture/ADR-002-Hermes-Memory-Agent.md).
- **2026-05-07**: Phase 2 SDKs landed. Python SDK (`pydantic` + `httpx`) and TypeScript SDK (`zod` + `fetch`) both implement schema + client + Tracer + decorator. Test suites green (15 py, 16 ts). Example agents emit live trace events through a mock transport. ADR recorded at `obsidian_vault/01_Architecture/ADR-001-SDK-Wedge.md`.
- **2026-05-06**: Repository structure initialized. CLAUDE.md, roadmap, and schemas drafted to prepare for autonomous agent development.
