---
skill: cynepic-guardian
status: active
description: Policy evaluator, circuit breaker, and trace store for agent actions
version: 0.2.0
language: Rust
binary: core-rs/target/release/trustlayer-guardian
default_endpoint: http://127.0.0.1:8089
links:
  - "[[../01_Architecture/ADR-004-Cynepic-Guardian-Policy-Engine]]"
  - "[[../01_Architecture/ADR-006-Phase-5-Dashboard-MCP]]"
---

# cynepic-guardian

Rust HTTP sidecar that evaluates `AgentTraceEvent`s against a
declarative policy and returns `PASS` / `FAIL` / `ESCALATE` with the
matching rule name. As of Phase 5 it also hosts the trace store that
the dashboard reads.

## Wire contract

```text
POST /v1/check
  { "event": <AgentTraceEvent>, "policy_name": "default" }
-> 200 { "decision": "PASS"|"FAIL"|"ESCALATE", "rule": ..., "reason": ..., "policy": ... }

POST /v1/events                                  (single event or array)
-> 200 { "stored": N }
GET  /v1/events?agent_id=&session_id=&event_type=&limit=N   -> [AgentTraceEvent]
GET  /v1/sessions                                -> [{agent_id, session_id, event_count, first_seen, last_seen}]
GET  /v1/sessions/:agent_id/:session_id          -> [AgentTraceEvent]
GET  /v1/reflections                             -> [{name, date}]
GET  /v1/reflections/:name                       -> {name, date, content}
GET  /healthz                                    -> 200 "ok"
```

Full request/response shapes: trace-store section of
[[../../docs/SCHEMA|SCHEMA.md]].

## Configuration
| Env var | Default | Purpose |
|---|---|---|
| `TRUSTLAYER_POLICY` | `policies/default.json` | Path to the CSL policy file. |
| `TRUSTLAYER_BIND` | `127.0.0.1:8089` | Listen address. |
| `TRUSTLAYER_EVENTS_PATH` | `events.jsonl` | Trace-store JSONL path; `""` = in-memory only. |
| `TRUSTLAYER_VAULT_PATH` | `obsidian_vault` | Vault root for `/v1/reflections` (reads `05_Reflections/`). |
| `RUST_LOG` | `info` | `tracing_subscriber` filter. |

## Run

```bash
# From core-rs/
cargo run --release --features server --bin trustlayer-guardian
```

## Cynefin-aware default
When no rule matches:
- `CHAOTIC` events default to `ESCALATE`.
- All other domains default to `PASS`.

## Layout
- `core-rs/src/schema.rs` — `AgentTraceEvent` mirror
- `core-rs/src/policy.rs` — `Policy`, `PolicyRule`, `MatchSpec`
- `core-rs/src/guardian.rs` — `CynepicGuardian::evaluate`
- `core-rs/src/events.rs` — `EventStore` (in-memory index + append-only JSONL)
- `core-rs/src/reflections.rs` — list/read Hermes reflection notes, path-traversal guarded
- `core-rs/src/server.rs` — Axum router + handlers (shared by binary and tests)
- `core-rs/src/bin/guardian.rs` — binary entry point
- `core-rs/policies/default.json` — example policy
- `core-rs/tests/cross_language.rs` — parses Pydantic-emitted JSON
- `core-rs/tests/http_events.rs` — HTTP integration tests for the trace store
- 47 Rust tests (31 lib unit + 4 cross-language + 12 HTTP integration)

## Python client
```python
from trustlayer import GuardianClient, AgentTraceEvent, EventType

with GuardianClient(policy_name="default", fail_open=True) as g:
    verdict = g.check(AgentTraceEvent(
        agent_id="a", session_id="s",
        event_type=EventType.TOOL_CALL,
        payload={"tool_name": "external_llm"},
    ))
    # verdict["decision"] in {"PASS", "FAIL", "ESCALATE"}
```
