# Current Status

**Phase:** Phase 4.6 — code-graph sense-making (Hermes importer) shipped; Phase 5 (Dashboard + MCP) next
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
- [ ] Build TrustLayer Dashboard (React/Vite).
- [ ] Build TrustLayer MCP Server for standard tool bridging.

## 📝 Recent Updates
- **2026-05-16** (latest): Phase 4.5 closed. Python `Tracer.check()` shipped (commit 3cccc6e, 4 new pytest cases) and TypeScript SDK gained `GuardianClient` + `Tracer.check()` parity (11 new vitest cases). All four layers green: Python 27/27, Hermes 44/44, Rust 19/19, TypeScript 27/27 — 117 tests total.
- **2026-05-13** (latest): Phase 4.6 — code-graph sense-making landed. New `skills/hermes/code_graph.py` with `CodeGraphImporter` (Pydantic v2 `CodeNode`/`CodeEdge`, generic JSON input), new `import-code-graph` CLI subcommand, output in a new `obsidian_vault/06_Code_Graph/` surface so the static code graph and runtime memory traces share one navigable vault. 11 new pytest cases, 44/44 total green. ADR-005 captures the design and the PolyForm Noncommercial licensing caveat on GitNexus. Two follow-up actions are user-gated (auto-classifier blocked agent-config self-modification and the global npm install).
- **2026-05-13** (later): Phase 4 — cynepic-guardian shipped. Rust core lib (schema mirror, CSL policy parser, ordered evaluator with Cynefin-aware default), Axum HTTP sidecar binary, Python `GuardianClient` (fail-open by default), 19/19 Rust tests + 8 new Python tests, live end-to-end smoke across FAIL/ESCALATE/PASS scenarios. ADR-004 captures the design.
- **2026-05-13**: Phase 3.5 — Hermes token/memory optimisation. Four bounded, opt-out-able knobs on `HermesAgent` (`max_payload_chars`, `max_cached_sessions`, `persist_events`, `state_path`); crash-resumable `reflect()`; LLM-friendly `SessionSummary.compact_text()`. 33/33 Hermes pytest cases passing. ADR-003 records the model. Also: `docs/ARCHITECTURE.md` rewritten with the actual three-layer data flow, `docs/SCHEMA.md` expanded to document every payload type, root `README.md` rewritten with concrete per-layer quickstarts, `CLAUDE.md` aligned with shipped phase status.
- **2026-05-10**: Phase 3 Hermes landed. `skills/hermes/` is now a real package: schema-typed ingestion, idempotent in-memory cache, per-session markdown notes, structural recursive reflection with a `ReflectionEngine` Protocol for future LLM swap-in, and a CLI. 18/18 pytest cases pass. Smoke run produced live notes in `obsidian_vault/03_Memory_Traces/` and `obsidian_vault/05_Reflections/`. Design recorded at [`obsidian_vault/01_Architecture/ADR-002-Hermes-Memory-Agent.md`](../obsidian_vault/01_Architecture/ADR-002-Hermes-Memory-Agent.md).
- **2026-05-07**: Phase 2 SDKs landed. Python SDK (`pydantic` + `httpx`) and TypeScript SDK (`zod` + `fetch`) both implement schema + client + Tracer + decorator. Test suites green (15 py, 16 ts). Example agents emit live trace events through a mock transport. ADR recorded at `obsidian_vault/01_Architecture/ADR-001-SDK-Wedge.md`.
- **2026-05-06**: Repository structure initialized. CLAUDE.md, roadmap, and schemas drafted to prepare for autonomous agent development.
