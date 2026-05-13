---
skill: cynepic-guardian
status: active
description: Policy evaluator and circuit breaker for agent actions
version: 0.1.0
language: Rust
binary: core-rs/target/release/trustlayer-guardian
default_endpoint: http://127.0.0.1:8089
links:
  - "[[../01_Architecture/ADR-004-Cynepic-Guardian-Policy-Engine]]"
---

# cynepic-guardian

Rust HTTP sidecar that evaluates `AgentTraceEvent`s against a
declarative policy and returns `PASS` / `FAIL` / `ESCALATE` with the
matching rule name.

## Wire contract

```text
POST /v1/check
  { "event": <AgentTraceEvent>, "policy_name": "default" }
-> 200
  { "decision": "PASS"|"FAIL"|"ESCALATE", "rule": "...", "reason": "...", "policy": "..." }

GET /healthz -> 200 "ok"
```

## Configuration
| Env var | Default | Purpose |
|---|---|---|
| `TRUSTLAYER_POLICY` | `policies/default.json` | Path to the CSL policy file. |
| `TRUSTLAYER_BIND` | `127.0.0.1:8089` | Listen address. |
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
- `core-rs/src/bin/guardian.rs` — Axum HTTP server
- `core-rs/policies/default.json` — example policy
- `core-rs/tests/cross_language.rs` — parses Pydantic-emitted JSON

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
