# TrustLayer Dashboard

React + Vite + TypeScript shell for the TrustLayer observability and policy
plane. Phase 5 scaffold — the four placeholder panes (Traces, Sessions,
Reflections, Policy) are not yet wired to a live data source.

The trace-store decision (read from JSONL? from a dedicated ingest endpoint
backed by the Rust sidecar? from Hermes's vault?) is captured in
[ADR-006](../obsidian_vault/01_Architecture/ADR-006-Phase-5-Dashboard-MCP.md).

## Quickstart

```bash
cd dashboard
npm install
npm run dev        # Vite dev server on http://localhost:5173
npm run typecheck  # tsc --noEmit, must stay clean
npm run build      # production build to dist/
```
