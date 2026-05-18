---
adr: 006
status: accepted
date: 2026-05-17
updated: 2026-05-18
tags: [architecture, phase-5, dashboard, mcp, observability]
supersedes: []
extends: ["[[ADR-001-SDK-Wedge]]", "[[ADR-002-Hermes-Memory-Agent]]", "[[ADR-004-Cynepic-Guardian-Policy-Engine]]"]
---

# ADR-006 — Phase 5: Dashboard + MCP Server

## Context
Phases 1–4 shipped the *write side* of TrustLayer: SDKs emit
`AgentTraceEvent`s ([[ADR-001-SDK-Wedge]]), Hermes materialises sessions
and reflections into the vault ([[ADR-002-Hermes-Memory-Agent]],
[[ADR-003-Hermes-Token-Memory-Model]]), and `cynepic-guardian`
adjudicates policy synchronously ([[ADR-004-Cynepic-Guardian-Policy-Engine]]).
Phase 4.6 added a static code graph surface ([[ADR-005-Code-Graph-Integration]]).

What's missing is the *read / extend* side:

1. A **dashboard** for humans to inspect the trace stream, sessions,
   reflections, and policy verdicts at a glance.
2. An **MCP server** so MCP-aware clients (Claude Code, the MCP
   Inspector, agents in production) can drive TrustLayer's tools
   without depending on the per-language SDKs.

Both can move in parallel. This ADR records the layout, language, and
transport decisions so the two scaffolds don't drift from the rest of
the monorepo.

## Decision

### Layout
Two new top-level directories at the repo root, matching the existing
flat shape (`core-rs/`, `sdks/`, `skills/`):

```
trustlayer/
├── dashboard/        — React + Vite + TypeScript shell
└── mcp-server/       — Python MCP server bridging SDK + Guardian + Hermes
```

We considered an `apps/` umbrella but rejected it — the repo is
deliberately flat so the architectural surfaces (core-rs, sdks, skills,
docs, obsidian_vault) sit at the same level as the user reading them.

### Dashboard

- **Stack:** React 18 + Vite 5 + TypeScript strict (matches the existing
  `sdks/typescript/` discipline).
- **Status in this ADR:** scaffold only. Four placeholder panes
  (Traces, Sessions, Reflections, Policy) hint at the intended surface.
- **Trace store (resolved 2026-05-18): option 3 — extend the Rust
  sidecar.** The existing `trustlayer-guardian` binary now also serves
  the trace-store read API:

    - `POST /v1/events`                                  — single event or batch
    - `GET /v1/events?agent_id=&session_id=&limit=N`     — filtered list
    - `GET /v1/sessions`                                 — per-pair summaries
    - `GET /v1/sessions/:agent/:session`                 — one session

  Persistence is append-only JSONL at `TRUSTLAYER_EVENTS_PATH`
  (default `./events.jsonl`; set to `""` for in-memory). The
  `EventStore` mirrors the Hermes JSONL pattern from [[ADR-003-Hermes-Token-Memory-Model]]
  — idempotent on `trace_id`, replay-on-open. Router lives in
  `core-rs/src/server.rs` so the binary and integration tests share
  one source of truth. CORS is permissive (`Any`) so the dashboard
  can fetch directly from a different port.

  The Traces pane is wired (`GET /v1/events?limit=50`, polled every 5s);
  Sessions / Reflections / Policy panes are still placeholders.

### MCP server

- **Language: Python.** Rationale:
    - Hermes is Python-only; an in-process import is dramatically
      simpler than another RPC hop.
    - The Python SDK is the most mature TrustLayer surface.
    - The official Python MCP SDK ships `FastMCP`, a decorator-based
      tool API that lines up perfectly with our existing `Tracer.emit`
      / `GuardianClient.check` shapes.
- **Transport: stdio for v1.** Every MCP client supports it; SSE adds
  HTTP infrastructure we don't need yet. Switching to SSE later is a
  one-line FastMCP change.
- **Tool surface (5 tools):**

  | MCP tool                          | Wraps                                |
  | --------------------------------- | ------------------------------------ |
  | `trustlayer_emit_event`           | `TrustLayerClient.emit`              |
  | `trustlayer_guardian_check`       | `GuardianClient.check`               |
  | `trustlayer_hermes_ingest`        | `HermesAgent.ingest[_jsonl]`         |
  | `trustlayer_hermes_get_session`   | `HermesAgent.session_events`         |
  | `trustlayer_hermes_reflect`       | `HermesAgent.reflect`                |

- **Handler shape:** each tool is a pure function in
  `trustlayer_mcp.tools`, taking a Pydantic input model and returning a
  JSON-serialisable dict. The `server.py` module is a thin
  `@mcp.tool()` wrapper. This lets us unit-test handlers without the
  MCP transport — pytest can call them directly with fake
  `TrustLayerClient` / `GuardianClient` factories and a tmpdir vault
  for Hermes. 12 pytest cases land with the scaffold.

## Consequences

- **+** TrustLayer is reachable from any MCP-aware agent — Claude Code,
  Inspector, future agent frameworks — without writing per-language
  bindings.
- **+** Handlers stay pure / testable; the MCP layer can be swapped or
  upgraded (stdio → SSE → HTTP/2) without rewriting the bridge logic.
- **+** The dashboard scaffold pins the visual contract early; we can
  build out a single pane at a time without rewriting Vite config.
- **−** Two more package managers in the repo (npm for dashboard,
  pip/hatch for mcp-server). Acceptable — the boundary is already
  polyglot.
- **−** The trace-store decision is explicitly deferred. The dashboard
  cannot show live data until that lands; we should not let that drag.

## Follow-ups
- Wire the Sessions pane to `GET /v1/sessions` (cheap — same fetch
  shape as the Traces pane) and the per-session drill-down to
  `GET /v1/sessions/:agent/:session`.
- Decide whether the Reflections pane reads vault markdown directly
  or goes through the MCP server's `trustlayer_hermes_reflect` tool.
  The latter keeps the contract uniform; the former skips a hop.
- Auth/token gating on the ingest routes (currently open). Acceptable
  for v0 because we listen on loopback only.
- Switch the sync `Mutex` in `EventStore` to a `tokio::sync::Mutex`
  if the JSONL write ever becomes a measured tail-latency problem;
  current writes are <100µs on local disk.
- Register the MCP server in `.claude/settings.json` once the auto-
  classifier permits agent-config edits (same blocker as the GitNexus
  follow-up from [[ADR-005-Code-Graph-Integration]]).
