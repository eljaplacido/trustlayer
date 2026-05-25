# Claude Code / Agentic Framework Guide

You are operating within **TrustLayer**, a polyglot monorepo for open
governance, observability, and trust for agentic AI.

## Project vision
TrustLayer acts as the middleware and observability plane for multi-agent
systems. It intercepts tool calls, evaluates policies (Rust core, Phase
4), tracks cost/latency, and builds a recursive memory graph via the
**Hermes** subagent into an Obsidian vault.

## Repository architecture
- `core-rs/` — high-performance Rust core: schema mirror, CSL policy
  parser, `cynepic-guardian` evaluator, Axum HTTP sidecar.
  **Phase 4, shipped.**
- `sdks/python/` — Python SDK for instrumenting Python agents. **Phase 2,
  shipped.**
- `sdks/typescript/` — TypeScript SDK for instrumenting JS agents.
  **Phase 2, shipped.**
- `sdks/go/` — Go SDK for instrumenting Go agents. Claims wire-format
  conformance (spec §6.2). **Phase 6 Slice 4b, shipped.**
- `skills/hermes/` — recursive memory subagent. **Phase 3, shipped.**
- `mcp-server/` — Python MCP server (FastMCP stdio) bridging SDK +
  Guardian + Hermes to MCP-aware clients. **Phase 5, shipped.**
- `dashboard/` — React + Vite + TypeScript shell for the observability
  UI. **Phase 5, scaffolded** (data source TBD — see ADR-006).
- `obsidian_vault/` — human-readable knowledge graph (architecture,
  agent skills, memory traces, reflections).
- `docs/` — architecture blueprints, schemas, and status tracking.

## Where the truth lives
- **Phase status** — `docs/CURRENT_STATUS.md`. Read it first. Update it
  when you finish a task.
- **Wire format** — `docs/SCHEMA.md`. This is the contract for every
  layer. Do not invent a second copy.
- **Architecture** — `docs/ARCHITECTURE.md`, plus ADRs in
  `obsidian_vault/01_Architecture/`.
- **Reasoning / decisions / reflections** — `obsidian_vault/` only,
  with valid YAML frontmatter. Never use generic log files for agent
  reasoning.

## Polyglot rules
- **Rust** — `cargo clippy` and `cargo fmt` must pass. Optimize for
  microsecond latency. No `unwrap()` on production paths.
- **Python** — 3.11+. Pydantic v2 for serialization. Type hints
  everywhere. `from __future__ import annotations` at the top of every
  module.
- **TypeScript** — strict mode, `noUncheckedIndexedAccess`. Export
  interfaces clearly.
- **Go** — `go vet ./...` clean. stdlib + `google/uuid` only. Schema
  parsers use `json.Decoder.DisallowUnknownFields()` semantics
  (W1 conformance). All public APIs take `context.Context` first.

## Build & test
```bash
# Python SDK
cd sdks/python && pip install -e .[dev] && pytest

# Hermes (requires the Python SDK installed first)
cd skills/hermes && pytest

# TypeScript SDK
cd sdks/typescript && npm install && npm run typecheck && npm test

# Go SDK
cd sdks/go && go vet ./... && go test ./...

# Rust core
cd core-rs && cargo test --features server
# Run the guardian HTTP sidecar:
cd core-rs && cargo run --release --features server --bin trustlayer-guardian

# MCP server (Python, FastMCP stdio)
cd mcp-server && python3 -m venv .venv && .venv/bin/pip install -e ../sdks/python -e .[dev]
PYTHONPATH=src:../sdks/python/src:../skills .venv/bin/python -m pytest
.venv/bin/trustlayer-mcp        # serve over stdio

# Dashboard (React + Vite)
cd dashboard && npm install && npm run typecheck && npm test && npm run build
npm run dev   # http://localhost:5173
```

## Hermes invocation
```bash
PYTHONPATH=skills python -m hermes.cli \
    --vault obsidian_vault \
    ingest path/to/traces.jsonl --reflect

# Mirror a GitNexus-style code graph into obsidian_vault/06_Code_Graph/.
# Expects <gitnexus-root>/graph.json (or nodes.json + edges.json).
PYTHONPATH=skills python -m hermes.cli \
    --vault obsidian_vault \
    import-code-graph --gitnexus-root .gitnexus
```

## Code-graph (GitNexus) prerequisites
The `import-code-graph` subcommand reads a JSON graph that GitNexus
produces. To populate `.gitnexus/` from this repo (one-time per machine):
```powershell
$env:GITNEXUS_SKIP_OPTIONAL_GRAMMARS = "1"   # skip native C++ grammar builds on Windows
npm install -g gitnexus@latest               # requires Node >= 22
npx gitnexus analyze                         # writes .gitnexus/ at the repo root
npx gitnexus serve                           # interactive Sigma.js web UI
```
GitNexus's MCP server is registered in `.claude/settings.json`; once
present, the 13 GitNexus tools (`query`, `cypher`, `context`, `impact`,
…) are callable directly from Claude Code. See
[ADR-005](obsidian_vault/01_Architecture/ADR-005-Code-Graph-Integration.md)
for the design and the PolyForm Noncommercial license caveat.

## Guardian invocation
```bash
# Start the policy server (default: 127.0.0.1:8089, policies/default.json)
cd core-rs && cargo run --release --features server --bin trustlayer-guardian

# From Python:
from trustlayer import GuardianClient, AgentTraceEvent, EventType
with GuardianClient(policy_name="default") as g:
    verdict = g.check(AgentTraceEvent(
        agent_id="a", session_id="s",
        event_type=EventType.TOOL_CALL,
        payload={"tool_name": "external_llm"},
    ))
```

## Working agreements
1. Tests are the contract for shipped behavior. New behavior gets a new
   test; refactors keep the existing ones green.
2. Instrumentation must never take down the host agent. Emit failures
   are logged and swallowed everywhere.
3. The SDKs mirror `docs/SCHEMA.md` byte-for-byte. If you change one,
   change the other in the same commit.
4. When introducing a new architectural decision, write an ADR in
   `obsidian_vault/01_Architecture/ADR-NNN-*.md` before merging the
   code. ADRs are dated and append-only.
