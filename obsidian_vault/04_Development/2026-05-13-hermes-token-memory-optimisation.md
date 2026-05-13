---
date: 2026-05-13
phase: 3.5
status: complete
tags: [development, hermes, optimization, tokenization, memory]
links:
  - "[[../01_Architecture/ADR-003-Hermes-Token-Memory-Model]]"
  - "[[../02_Agent_Skills/Hermes_Manifest]]"
  - "[[../../docs/CURRENT_STATUS]]"
---

# Phase 3.5 — Hermes Token / Memory Optimisation

## What landed
- `HermesAgent` grew four knobs: `max_payload_chars`,
  `max_cached_sessions`, `persist_events`, `state_path`.
- Payload truncation walks the event payload recursively, clipping any
  string past `max_payload_chars` with a `<...truncated N chars>`
  marker.
- JSONL sidecars at `<vault>/.hermes_state/<agent>/<session>.events.jsonl`
  are append-only and dedupe on `trace_id`; they are the canonical
  record of every ingested event.
- LRU eviction keeps `_sessions` bounded. The evicted session's
  markdown note is flushed before its events leave memory.
- `reflect()` is now crash-resumable: it discovers sessions from both
  the in-memory cache and the sidecar directory, so a daily reflection
  job survives Hermes restarts.
- `SessionSummary.compact_text(max_chars=600)` produces a token-lean
  one-line summary ready for LLM reflection prompts.
- 15 new pytest cases (33 total in the Hermes suite). All green.

## Why these choices
See [[../01_Architecture/ADR-003-Hermes-Token-Memory-Model]]. The
shortest version: a real agent stack produces 10 KB–1 MB payloads,
hundreds of events per session, and runs Hermes for days. Without these
knobs the vault becomes unreadable, the process leaks linearly, and a
crash loses everything that wasn't already on disk.

## Defaults are deliberate
The defaults assume "running Hermes inline next to an instrumented
agent for a working day":
- 2 000 char truncation keeps notes navigable in Obsidian while
  preserving enough context to debug a tool call.
- 256 session cache is roughly 64 MB of Python objects in the worst
  case — fine for a workstation, conservative for a server.
- Sidecar persistence on by default so anyone copying the SDK example
  gets crash-resume for free.

## Next up (Phase 4 — Rust core)
- CSL/policy parser in `core-rs`.
- `cynepic-guardian` circuit breaker (`PASS`/`FAIL`/`ESCALATE`).
- FFI or HTTP gateway so the SDKs can call the guardian inline.
- ADR-004 capturing the policy language design.

## Open question for the next session
The Rust toolchain (cargo/rustc/rustup) is not available on this
machine. Three viable paths for Phase 4: (a) install rustup and ship
the Rust core as planned, (b) ship a Python prototype in
`services/guardian/` with the same HTTP contract, swap to Rust later,
(c) re-prioritise and jump to Phase 5 (dashboard + MCP server).
