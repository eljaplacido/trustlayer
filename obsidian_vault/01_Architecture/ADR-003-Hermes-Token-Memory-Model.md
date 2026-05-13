---
adr: 003
status: accepted
date: 2026-05-13
tags: [architecture, hermes, memory, tokenization, observability]
supersedes: []
extends: "[[ADR-002-Hermes-Memory-Agent]]"
---

# ADR-003 — Hermes Context / Token / Memory Model

## Context
ADR-002 shipped Hermes with an unbounded in-memory cache and full-payload
markdown rendering. That is fine for tens of sessions and sub-KB
payloads, but a real agent stack produces:

- 10 KB–1 MB tool results (search hits, page bodies, code blobs)
- Sessions with hundreds of events when the agent is long-running
- Many concurrent sessions across multiple agents

Three failure modes follow from leaving those unbounded:

1. **Token bloat in the vault.** Each event's full JSON payload is
   rendered into the markdown note. A handful of long LLM completions
   makes a single session note exceed an LLM's context window — exactly
   the input we want the (future) LLM-backed reflector to chew on.
2. **Memory blowup in the Hermes process.** `_sessions` holds every
   `AgentTraceEvent` for every key we've ever seen. A daemonised Hermes
   leaks linearly.
3. **No crash resume.** Restart Hermes and the cache is gone. Notes on
   disk capture the rendered view but not the structured events that
   feed reflection.

## Decision
Add four bounded, opt-out-able knobs to `HermesAgent` and one
LLM-friendly method on `SessionSummary`.

### 1. Payload truncation (`max_payload_chars`, default 2_000)
Walk the event payload recursively. Any string longer than the limit is
clipped and tagged: `"<...truncated N chars>"`. Dicts/lists are
traversed; numbers, booleans, and short strings pass through. Setting
`max_payload_chars <= 0` disables truncation.

Truncation happens **before** the event enters the cache, so both the
markdown note and the JSONL sidecar see the same truncated value. This
is an explicit tradeoff: we lose the original payload if we want to
re-render with a different limit. Acceptable because the SDK always
holds the canonical pre-truncation event; if you need the full body,
re-ingest the raw JSONL with the limit relaxed.

### 2. JSONL sidecar (`persist_events=True`, `state_path=<vault>/.hermes_state`)
Each newly-ingested event (by `trace_id`) is appended to
`<state_path>/<agent>/<session>.events.jsonl`. The sidecar is the canonical
record; the in-memory cache is a derived view that can be evicted at any
time without data loss. `reflect()` rehydrates evicted sessions from
sidecars so a daily reflection job can run after Hermes restarts.

State lives outside the human-facing vault by default (dot-prefixed
directory, which Obsidian skips). Per ADR-002's "no generic log files
for reasoning" rule, the sidecar is **structured operational data, not
reasoning** — Hermes' reasoning still lands only in markdown notes.

### 3. Bounded LRU cache (`max_cached_sessions=256`)
On every `ingest()`, the affected session key is moved to the tail of an
`OrderedDict[SessionKey, None]`. When the cache size exceeds the bound,
the head is popped and removed from `_sessions`. The markdown note for
the evicted session was already flushed during that ingest call, so the
human view stays current; the sidecar persists the raw events. Set to
`None` to disable eviction (acceptable for batch jobs).

### 4. `SessionSummary.compact_text(max_chars=600)`
A one-line, pipe-separated summary suitable for stuffing many sessions
into a single LLM reflection prompt. Form:

```
agent/session | events=N | wall=12.3s | tool_latency=145ms | tools[calc=2, search=1] | errors=1 | policy_fail[pii:send_to_llm]
```

Capped by `max_chars` with a `...` tail. This is what a future
`ClaudeReflector` will use to fit hundreds of sessions into a single
prompt.

## Consequences

### Positive
- A single session note is now bounded to roughly
  `max_payload_chars × max_events_per_session` characters even with
  pathological tool outputs.
- Hermes process memory is bounded: O(`max_cached_sessions` × average
  session size).
- Reflection is crash-resumable. Daily jobs can run after a restart and
  see every session that ever happened on disk.
- LLM reflection has a token-aware shape it can use without re-deriving
  one.

### Negative
- Sidecar JSONL is append-only — pruning old data requires deleting
  files manually. Acceptable for v1; a `prune()` method is a follow-up.
- Truncation is destructive at the sidecar level. If you must keep the
  raw payload, run Hermes with `max_payload_chars=0` and rely on cache
  bounds + LRU eviction alone.
- `_all_known_keys()` scans the sidecar directory on every `reflect()`.
  O(sessions) on disk; replace with an index file if it ever shows up
  in profiles.

## Links
- [[ADR-002-Hermes-Memory-Agent]]
- [[../../docs/SCHEMA.md]]
- [[../../docs/ARCHITECTURE.md]]
- [[../02_Agent_Skills/Hermes_Manifest]]
