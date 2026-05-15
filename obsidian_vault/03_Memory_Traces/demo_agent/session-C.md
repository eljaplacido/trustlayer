---
agent_id: demo_agent
session_id: session-C
started_at: "2026-05-15T05:45:06.385849+00:00"
ended_at: "2026-05-15T05:45:06.388741+00:00"
event_count: 4
tags: [memory-trace, agent/demo_agent]
---

# Session `session-C` — agent `demo_agent`

## Timeline

### `AGENT_START`
- timestamp: `2026-05-15T05:45:06.385849+00:00`
- cynefin: `COMPLEX`
- payload: `{"goal": "C. ESCAL   human_callout in COMPLEX"}`

### `TOOL_CALL`
- timestamp: `2026-05-15T05:45:06.386588+00:00`
- cynefin: `COMPLEX`
- payload: `{"tool_args": {"q": "hello"}, "tool_name": "human_callout"}`

### `POLICY_CHECK`
- timestamp: `2026-05-15T05:45:06.388314+00:00`
- cynefin: `COMPLEX`
- payload: `{"action": "invoke human_callout", "policy_name": "default", "reason": "Complex-domain human callouts require an oncall review.", "result": "ESCALATE"}`

### `AGENT_END`
- timestamp: `2026-05-15T05:45:06.388741+00:00`
- cynefin: `COMPLEX`
- payload: `{"status": "ESCALATE"}`
