---
adr: 006
status: accepted
date: 2026-05-17
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
- **Deferred decision — trace store:** the dashboard needs *some* way
  to read the live event stream. Three candidates:
    1. Read JSONL files (simplest, matches the current
       `examples/end_to_end_demo.py` output but doesn't scale).
    2. Read directly from Hermes vault notes (free for free — Hermes
       already writes structured markdown — but human-friendly
       formatting is the wrong contract for a UI).
    3. Add a small ingest service backed by the Rust sidecar (cleanest
       long-term; biggest scope).
  This ADR explicitly punts the choice — the scaffold compiles and
  builds, but no pane fetches data yet. Whichever data path we pick,
  the four-pane shape stays.

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
- Pick the dashboard's data source (the three candidates above) and
  wire the Traces pane first.
- Sessions/Reflections panes can read directly from
  `obsidian_vault/03_Memory_Traces/` and `obsidian_vault/05_Reflections/`
  via the MCP server's `hermes_get_session` + `hermes_reflect` tools
  — i.e. dashboard ↔ MCP server, not dashboard ↔ filesystem. Decide
  before implementing.
- Register the MCP server in `.claude/settings.json` once the auto-
  classifier permits agent-config edits (same blocker as the GitNexus
  follow-up from [[ADR-005-Code-Graph-Integration]]).
