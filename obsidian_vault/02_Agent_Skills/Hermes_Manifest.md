---
skill: hermes
status: active
description: Recursive memory and reflection subagent
version: 0.2.0
entry_point: skills/hermes/cli.py
schema_owner: trustlayer.schema.AgentTraceEvent
links:
  - "[[../01_Architecture/ADR-002-Hermes-Memory-Agent]]"
  - "[[../01_Architecture/ADR-003-Hermes-Token-Memory-Model]]"
---

# Hermes

Hermes consumes `AgentTraceEvent` records from the TrustLayer SDKs and
materialises them into the Obsidian vault. Memory- and token-bounded by
design (see [[../01_Architecture/ADR-003-Hermes-Token-Memory-Model]]).

## Responsibilities
- **Ingest.** Group events by `(agent_id, session_id)`, deduplicate by
  `trace_id`, write one markdown note per session to
  `03_Memory_Traces/<agent>/<session>.md`. Truncates oversized payload
  strings inline.
- **Persist.** Append every unique event to
  `.hermes_state/<agent>/<session>.events.jsonl` so the cache can be
  evicted without losing data.
- **Reflect.** Walk known sessions (cache + sidecars) and produce a
  dated reflection note in `05_Reflections/`.
- **Stay bounded.** LRU-evicts in-memory sessions when
  `max_cached_sessions` is exceeded. Re-loads from sidecars on demand.

## Configuration knobs

| Knob | Default | Effect |
|---|---|---|
| `max_payload_chars` | `2_000` | Truncate every string in event payload past this length. `0` disables. |
| `max_cached_sessions` | `256` | LRU eviction threshold for `_sessions`. `None` disables. |
| `persist_events` | `True` | Append unique events to JSONL sidecars. Disable for ephemeral runs. |
| `state_path` | `<vault>/.hermes_state` | Where sidecars live. Override to keep state outside the vault. |
| `reflector` | `DeterministicReflector()` | Anything satisfying `ReflectionEngine`; future LLM impls go here. |

## Invocation

```bash
pip install -e sdks/python

PYTHONPATH=skills python -m hermes.cli \
    --vault obsidian_vault \
    ingest path/to/traces.jsonl --reflect
```

## Layout
- `skills/hermes/hermes_agent.py` — `HermesAgent`
- `skills/hermes/reflector.py` — `ReflectionEngine` Protocol +
  `DeterministicReflector` + `SessionSummary.compact_text()`
- `skills/hermes/render.py` — markdown rendering
- `skills/hermes/cli.py` — `python -m hermes.cli`
- `skills/hermes/tests/` — 33 pytest cases
