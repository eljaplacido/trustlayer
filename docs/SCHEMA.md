# TrustLayer Event Schema

TrustLayer uses an OpenTelemetry-inspired schema for tracking agentic
execution. **This document is the contract.** Both SDKs serialise to
the same shape, and the Rust core (Phase 4) plus Hermes (Phase 3) consume
it without re-deriving types.

| Layer | Implementation |
|---|---|
| Python | `sdks/python/src/trustlayer/schema.py` (Pydantic v2) |
| TypeScript | `sdks/typescript/src/schema.ts` (Zod) |
| Rust | `core-rs/src/schema.rs` (serde) |

## AgentTraceEvent

The envelope for every event emitted by an agent.

```json
{
  "trace_id": "uuid-v4",
  "agent_id": "string",
  "session_id": "string",
  "timestamp": "ISO-8601 with offset (e.g. 2026-05-12T09:00:00+00:00)",
  "event_type": "AGENT_START | TOOL_CALL | TOOL_RESULT | LLM_CALL | POLICY_CHECK | HUMAN_ESCALATION | AGENT_END",
  "cynefin_domain": "CLEAR | COMPLICATED | COMPLEX | CHAOTIC | DISORDER",
  "payload": { /* event-specific, see below */ },
  "metrics": {
    "latency_ms": 120.5,
    "cost_usd": 0.0015,
    "tokens_prompt": 150,
    "tokens_completion": 45
  }
}
```

### Rules
- `trace_id` is **per event**, not per session. Group by `session_id`
  for a logical agent run.
- `timestamp` must include a UTC offset. Emitters default to `now(utc)`.
- `cynefin_domain` defaults to `DISORDER` (unknown). The
  [Cynefin framework](https://en.wikipedia.org/wiki/Cynefin_framework)
  classifies the decision context — agents should set this when they
  know, otherwise leave it default.
- `payload` is event-type specific. Unknown keys are tolerated for
  forward compatibility, but emitters should stay within the shapes
  below.
- `metrics` accepts extra keys (Pydantic `extra="allow"`, Zod
  `.passthrough()`) so custom telemetry can ride along.

## Payloads

### `TOOL_CALL`
```json
{
  "tool_name": "string",
  "tool_args": { /* arbitrary JSON-able key/value */ }
}
```

### `TOOL_RESULT`
```json
{
  "tool_name": "string",
  "result": null,         // success result, any JSON value
  "error": null           // error message; mutually exclusive with result
}
```

### `LLM_CALL`
```json
{
  "model": "string",      // e.g. "claude-opus-4-7"
  "prompt": "string",     // optional — caller decides what to log
  "completion": "string"  // optional — populate on LLM_RESULT-style usage
}
```

### `POLICY_CHECK`
```json
{
  "policy_name": "string",
  "action": "string",
  "result": "PASS | FAIL | ESCALATE",
  "reason": "string"
}
```

### `AGENT_START` / `AGENT_END` / `HUMAN_ESCALATION`
Free-form payload. Common keys: `goal`, `status`, `reason`. Emitters
choose what to capture.

## Guardian Verdict (response from `cynepic-guardian`)

`POST /v1/check` returns this shape. The Python `GuardianClient.check()`
deserialises into a `TypedDict` of the same name.

```json
{
  "decision": "PASS | FAIL | ESCALATE",
  "rule": "name-of-matching-rule-or-null",
  "reason": "human-readable explanation or null",
  "policy": "default"
}
```

- `decision` shares the enum domain with `POLICY_CHECK.payload.result`,
  so a verdict can be recorded verbatim as the `result` of a follow-up
  `POLICY_CHECK` event without translation.
- `rule` is `null` when the default branch fired (no rule matched).
- `reason` is `null` for `PASS`-by-default; populated for Cynefin
  `CHAOTIC` escalations and any rule that carries its own reason text.

## Compatibility

| Change | Impact |
|---|---|
| Add a new `event_type` value | Minor — old consumers will accept it via passthrough on `payload` but won't recognise the literal in `event_type` enums; bump SDKs together. |
| Add a key to `payload` | Backward compatible by design (payload is `dict[str, Any]`). |
| Add a top-level field | Breaking — both SDKs use strict envelope validation (`extra="forbid"` / Zod `.strict()`). Coordinate releases. |
| Change `metrics` field type | Breaking — metrics is `passthrough` but typed; rename the field instead of repurposing it. |
