---
adr: 005
status: accepted
date: 2026-05-13
tags: [architecture, hermes, code-graph, observability]
supersedes: []
extends: "[[ADR-002-Hermes-Memory-Agent]]"
---

# ADR-005 — Code-Graph Sense-Making via GitNexus

## Context
TrustLayer's runtime story is in good shape: SDKs emit
`AgentTraceEvent`s (see [[ADR-001-SDK-Wedge]]), Hermes materialises
sessions into `obsidian_vault/03_Memory_Traces/` (see
[[ADR-002-Hermes-Memory-Agent]]), and `cynepic-guardian` evaluates
policy synchronously (see [[ADR-004-Cynepic-Guardian-Policy-Engine]]).

What we don't have is a **static** view of the code those agents are
written against. For a polyglot monorepo (Rust + Python + TypeScript)
the gap matters:

- Refactors are risky because no tool answers "what calls into
  `trustlayer.schema`?" across all three languages.
- Onboarding is slow — the architecture lives in prose docs, not a
  navigable structure.
- Hermes can correlate sessions to other sessions but not to the
  *code* that produced them.

Building a Tree-sitter → graph-DB → web-UI stack inside Hermes would
take months and reinvent prior art. GitNexus
(https://github.com/abhigyanpatwari/GitNexus) already ships exactly
this: 16-language Tree-sitter indexer, embedded graph DB, MCP server
with 13 tools (`query`, `cypher`, `context`, `impact`, `route_map`,
`tool_map`, `shape_check`, `api_impact`, `group_list`, `group_sync`,
`detect_changes`, `rename`, `list_repos`), and a Sigma.js/WebGL web
UI. Rust, Python, and TypeScript are all first-class.

## Decision

### 1. Consume GitNexus as the indexing/visualization engine
TrustLayer does not re-implement Tree-sitter parsing, graph storage,
or graph visualization. It installs GitNexus as a CLI dependency
(`npm install -g gitnexus`), runs `npx gitnexus analyze` against the
monorepo root to produce a per-repo `.gitnexus/` index, and uses
`npx gitnexus serve` for the interactive Sigma.js graph view. The
`.gitnexus/` directory is per-machine state and `.gitignore`d
alongside `target/` and `.hermes_state/`.

### 2. GitNexus MCP server is wired into Claude Code
A new `.claude/settings.json` declares the gitnexus MCP server with
the Windows-correct shim (`cmd /c npx -y gitnexus@latest mcp`). The
13 MCP tools become callable directly from the agent runtime so
refactor-impact and call-graph questions can be answered without
context-switching to the web UI.

### 3. Hermes mirrors the code graph into the vault
A new module, `skills/hermes/code_graph.py`, defines a
`CodeGraphImporter` that reads a JSON graph
(`{nodes: [...], edges: [...]}`) and emits one Obsidian markdown note
per node into `obsidian_vault/06_Code_Graph/<language>/<safe_id>.md`.
Edges become `[[wikilinks]]` so the static code graph is navigable
inside Obsidian's native graph view, side-by-side with
`03_Memory_Traces/` and `05_Reflections/`. This is the "sense-making"
half of the deliverable — humans navigate the same vault for runtime
*and* static perspectives.

The importer reads `<gitnexus-root>/graph.json` by default; if absent,
falls back to `<gitnexus-root>/nodes.json` + `<gitnexus-root>/edges.json`.
The on-disk format produced by `npx gitnexus analyze` is not formally
documented upstream, so the importer is decoupled from it: a thin
shim (future) can dump GitNexus's internal index to this JSON shape
via `npx gitnexus query`. This keeps tests hermetic — they construct
synthetic JSON graphs without needing GitNexus installed.

### 4. Filename and wikilink conventions match ADR-002
`code_graph.py` reuses `hermes_agent._safe()` for filename
sanitization and `render._yaml_lines` / `_yaml_scalar` for
frontmatter rendering. Wikilinks omit the `.md` extension and are
relative to the vault root, matching `render.render_reflection_note`
(`render.py:70`).

### 5. CLI parity
`python -m hermes.cli --vault <vault> import-code-graph
[--gitnexus-root <path>]` is added as a third subcommand alongside
`ingest` and `reflect`. The contract: one subprocess invocation,
JSON in → markdown out, idempotent on re-run.

## Consequences

### Positive
- The web visualization deliverable is ~10 minutes of `npm install`,
  not three months of implementation.
- All 13 MCP tools (`impact`, `route_map`, `cypher`, etc.) become
  available to Claude Code automatically once `settings.json` is in
  place — no per-tool bridge code in TrustLayer.
- The Obsidian vault becomes a unified surface: a code-function note
  can backlink to the memory traces that exercised it, and a memory
  trace can `[[wikilink]]` to the function that emitted it.
- The mirror is decoupled from GitNexus's internal storage format,
  so an upstream version bump can't silently break us.
- Polyglot is solved upstream: Rust + Python + TypeScript all index
  through one tool with one CLI.

### Negative
- **License**: GitNexus is PolyForm Noncommercial. TrustLayer can
  consume it for development sense-making freely; commercial
  distribution of TrustLayer cannot bundle GitNexus. This must
  remain a development-time dependency and an *optional* runtime
  one. Codified by keeping `code_graph.py` free of any GitNexus
  imports — it reads a generic JSON shape.
- **Node ≥22 requirement** for GitNexus CLI. Documented in
  `CLAUDE.md` as a prerequisite.
- **Windows native-grammar builds** may fail without a C++ toolchain.
  Mitigation: set `GITNEXUS_SKIP_OPTIONAL_GRAMMARS=1` before
  `npm install -g gitnexus`. Documented in `CLAUDE.md`.
- The 13 MCP tools are not specified by TrustLayer; their behavior
  and tool names are upstream-defined and may shift across GitNexus
  versions.

## Links
- [[ADR-001-SDK-Wedge]]
- [[ADR-002-Hermes-Memory-Agent]]
- [[ADR-003-Hermes-Token-Memory-Model]]
- [[ADR-004-Cynepic-Guardian-Policy-Engine]]
- Schema: [[../../docs/SCHEMA.md]]
- Architecture: [[../../docs/ARCHITECTURE.md]]
- Upstream: https://github.com/abhigyanpatwari/GitNexus
