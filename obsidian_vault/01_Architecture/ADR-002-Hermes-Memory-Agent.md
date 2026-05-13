---
adr: 002
status: accepted
date: 2026-05-10
tags: [architecture, hermes, memory, reflection]
---

# ADR-002 — Hermes Memory Agent: Schema-Typed Ingestion + Pluggable Reflection

## Context
TrustLayer needs a subagent that consumes the trace stream produced by the
SDKs (see [[ADR-001-SDK-Wedge]]) and turns it into something a human can
navigate. The vault is the human-understanding layer; everything Hermes
emits must be valid Obsidian markdown.

We also need to leave room for an LLM-backed reflection pass without
shipping one yet — the structural data (tool frequency, policy failures,
latency totals) is enough for a first cut and tests deterministically.

## Decision
- **Single source of truth for events.** Hermes imports
  `trustlayer.schema.AgentTraceEvent` directly. There is no second copy of
  the schema inside the skill, so the wire format cannot drift.
- **In-memory, idempotent cache.** Events accumulate in
  `HermesAgent._sessions`, keyed by `(agent_id, session_id)` and deduped
  on `trace_id`. Re-ingesting the same JSONL is a no-op. Persistence is
  externalised: replay JSONL to rebuild the cache after a restart.
- **One file per session.** Each `(agent_id, session_id)` writes a single
  markdown note at
  `obsidian_vault/03_Memory_Traces/<agent>/<session>.md` with YAML
  frontmatter + a chronologically-ordered timeline. Filenames are
  sanitised so arbitrary IDs cannot escape the vault.
- **Pluggable reflection.** `ReflectionEngine` is a `typing.Protocol` with
  two methods: `summarise_session(events)` and `synthesise(summaries)`.
  The shipped `DeterministicReflector` produces structural metrics
  (tool counts, policy failures, latency totals). An LLM-backed reflector
  is a future ADR — likely a `ClaudeReflector` that takes
  `SessionSummary` inputs and produces prose insights.
- **Pluggable storage stays implicit for now.** Notes are written to disk
  with `pathlib.Path.write_text`. If we ever need a remote vault, we'll
  introduce a `VaultBackend` Protocol; until then, file IO inline is fine.
- **Output uses no emojis.** This keeps the rendered notes consistent
  across Obsidian themes and avoids encoding surprises.

## Consequences
- The Rust core (Phase 4) and any future evaluator can rely on
  `obsidian_vault/03_Memory_Traces/` as a stable location for the
  human-readable trace history.
- A future LLM reflector can be added without touching `HermesAgent` or
  `render.py`; only `reflector.py` (or a sibling module) changes.
- Re-running ingest is safe by construction. CI can re-feed trace fixtures
  on every test run without polluting the vault.
- Sanitising filenames means the vault path on disk is not a perfect
  inverse of the ID; the in-frontmatter `agent_id` / `session_id` remain
  the canonical identifiers.

## Links
- Schema: [[../../docs/SCHEMA.md]]
- Architecture: [[../../docs/ARCHITECTURE.md]]
- Status: [[../../docs/CURRENT_STATUS.md]]
- Hermes manifest: [[../02_Agent_Skills/Hermes_Manifest.md]]
- Phase 2 ADR: [[ADR-001-SDK-Wedge]]
