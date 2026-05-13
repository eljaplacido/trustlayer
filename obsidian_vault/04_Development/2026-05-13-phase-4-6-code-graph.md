---
date: 2026-05-13
phase: 4.6
status: complete
tags: [development, milestone, hermes, code-graph, observability]
links:
  - "[[../01_Architecture/ADR-005-Code-Graph-Integration]]"
  - "[[../../docs/CURRENT_STATUS]]"
---

# Phase 4.6 — Code-Graph Sense-Making (via GitNexus)

## What landed
- **ADR-005** — records the decision to consume GitNexus
  (https://github.com/abhigyanpatwari/GitNexus) as the indexing and
  visualization engine instead of rebuilding the stack inside Hermes.
  Notes the PolyForm Noncommercial license constraint.
- **`skills/hermes/code_graph.py`** — new module with `CodeNode`,
  `CodeEdge`, `CodeGraph` (Pydantic v2) and `CodeGraphImporter`. Reads
  a generic JSON graph (`graph.json` or `nodes.json + edges.json`) and
  emits one Obsidian note per node into
  `obsidian_vault/06_Code_Graph/<language>/<safe_id>.md` with YAML
  frontmatter and `[[wikilink]]` edges (Calls / Called by / Imports /
  Imported by / Inherits / Contains).
- **CLI** — `python -m hermes.cli --vault <vault> import-code-graph
  [--gitnexus-root <path>]` added as a third subcommand alongside
  `ingest` and `reflect`.
- **Tests** — 11 new pytest cases in `test_code_graph.py`. All 44
  Hermes tests pass (33 prior + 11 new).
- **`.gitignore`** — `.gitnexus/` (generated per-repo index) added
  alongside `target/` and `obsidian_vault/.hermes_state/`.

## What did NOT land in this commit (user action required)
- **`.claude/settings.json`** — declaring the GitNexus MCP server
  block. The auto-classifier blocked the write because registering
  an external MCP server is agent-config self-modification that
  needs explicit user authorization. Snippet to paste:
  ```json
  {
    "mcpServers": {
      "gitnexus": {
        "command": "cmd",
        "args": ["/c", "npx", "-y", "gitnexus@latest", "mcp"]
      }
    }
  }
  ```
- **`npm install -g gitnexus@latest`** — also blocked by the
  auto-classifier (global install of a third-party noncommercial
  package). Run manually with `$env:GITNEXUS_SKIP_OPTIONAL_GRAMMARS = "1"`
  set first on Windows.

## Why these choices
See [[../01_Architecture/ADR-005-Code-Graph-Integration]]. Highlights:
GitNexus already covers Tree-sitter parsing for 16 languages
(Rust/Python/TS all included), an embedded graph DB, 13 MCP query
tools, and a Sigma.js/WebGL web UI. Rebuilding any of that inside
Hermes would be months for a worse result. The bridge piece is a
generic-JSON importer so the GitNexus internal storage format can
shift without breaking the Obsidian mirror.

## How to use it end-to-end (once the user steps are done)

```powershell
# 1) Install (once)
$env:GITNEXUS_SKIP_OPTIONAL_GRAMMARS = "1"
npm install -g gitnexus@latest

# 2) Index the monorepo (from C:\Users\EljaPlacido\trustlayer)
npx gitnexus analyze

# 3) Launch the interactive web visualization (Sigma.js)
npx gitnexus serve     # opens local backend; follow URL it prints

# 4) Mirror the graph into the Obsidian vault as markdown
#    (assumes the importer can find a graph.json under .gitnexus/;
#     if not, dump nodes/edges to JSON via `npx gitnexus query`)
PYTHONPATH=skills python -m hermes.cli \
    --vault obsidian_vault \
    import-code-graph --gitnexus-root .gitnexus
```

After step 4, open the vault in Obsidian and turn on the graph view —
code nodes and runtime memory-trace nodes share the same wikilink
namespace.

## Known gaps
- The importer assumes `<gitnexus-root>/graph.json` or
  `nodes.json + edges.json`. GitNexus's actual `.gitnexus/` layout is
  not documented upstream; a small dumper (running
  `npx gitnexus query` with a Cypher node/edge dump and writing
  `graph.json`) will likely be needed at first real use, and may
  become a follow-up CLI subcommand.
- The 13 GitNexus MCP tool names are upstream-defined and may shift
  across versions.
- PolyForm Noncommercial license on GitNexus means the integration
  is development-time / non-commercial-use only by default. ADR-005
  flags this; commercial distribution of TrustLayer would need to
  make this an optional pluggable layer.

## Next up
- Once `.claude/settings.json` is in place, validate that
  `gitnexus__query`, `gitnexus__context`, `gitnexus__impact`, etc.
  are visible from Claude Code and call cleanly.
- Add a `gitnexus query --json` dumper helper (or CLI subcommand) so
  step 4 doesn't require manually shaping `graph.json`.
- Cross-link a `06_Code_Graph/` note to its matching
  `03_Memory_Traces/` notes once we have a session that exercised
  the same code path.
