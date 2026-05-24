# TrustLayer Event Schema

**`SCHEMA_VERSION = 0.2`** — see `docs/VERSIONING.md`. `0.2` is the
first version that documents the `MatchSpec.payload` predicate field
(ADR-008); the wire envelope itself is unchanged from `0.1`.

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

## Policy / `MatchSpec`

Policies (`core-rs/policies/*.json`) are an ordered list of rules. Each
rule has a `MatchSpec` selector and a `decision`. The selector predicates
AND together; an unset field matches any value. The first matching rule
wins.

```json
{
  "name": "default",
  "rules": [
    {
      "name": "block_gpt4_external",
      "match": {
        "event_type": "TOOL_CALL",
        "tool_name": "external_llm",
        "agent_id": "researcher-1",
        "cynefin_domain": "COMPLEX",
        "payload": {
          "model": "gpt-4",
          "args.temperature": 1.0,
          "args.tools.0": "shell"
        }
      },
      "decision": "FAIL",
      "reason": "GPT-4 + shell tool from researcher in COMPLEX domain"
    }
  ]
}
```

### `MatchSpec` fields

| Field | Type | Matches when… |
|---|---|---|
| `event_type` | `EventType` enum | the event's `event_type` equals this. |
| `tool_name` | string | the event's `payload.tool_name` equals this. Syntactic sugar for `payload: { "tool_name": "..." }`; kept for back-compat. |
| `agent_id` | string | the event's `agent_id` equals this. |
| `cynefin_domain` | `CynefinDomain` enum | the event's `cynefin_domain` equals this. |
| `payload` | `map<dotted-path, json>` | **every** dotted path in the map resolves to a value deep-equal to its JSON literal (ADR-008). |

### `payload` predicate semantics (ADR-008)

- Keys are dotted paths into `event.payload`. `"model"` ↦ `payload.model`;
  `"args.temperature"` ↦ `payload.args.temperature`;
  `"args.tools.0"` ↦ first element of `payload.args.tools` (numeric
  segments index arrays).
- Values are arbitrary JSON literals. Equality is **deep**: `"args":
  {"temperature": 1.0}` matches the whole nested object.
- Predicates AND together. A path that doesn't resolve (missing key,
  walking through a scalar, out-of-range index) **does not match**.
- `null` literals match `null` values only — not missing keys. There is
  no "absent equals null" coercion and no operators (`>`, regex, etc.).
- No type coercion: `1` does not match `1.0`, `"true"` does not match
  `true`. Match against the literal you mean.

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

## Trace-store HTTP API (Phase 5)

The `trustlayer-guardian` binary also serves a read/write trace store
that the dashboard consumes. All bodies are `AgentTraceEvent`-shaped or
derived from it; nothing here introduces a second envelope.

### `POST /v1/events`
Accepts a single `AgentTraceEvent` **or** a JSON array of them — this is
exactly what `TrustLayerClient.emit` / `emit_batch` already send.
Idempotent on `trace_id`.

```json
// response
{ "stored": 2 }   // count of newly-stored (non-duplicate) events
```

### `GET /v1/events?agent_id=&session_id=&event_type=&limit=N`
Every query parameter is optional. `event_type` takes one of the
`event_type` enum values; `limit` returns the most-recent N. Response is
a chronological `AgentTraceEvent[]`.

### `GET /v1/sessions`
One summary per `(agent_id, session_id)` pair, most-recent first:

```json
[
  {
    "agent_id": "researcher-1",
    "session_id": "S1",
    "event_count": 12,
    "first_seen": "2026-05-22T10:00:00+00:00",
    "last_seen": "2026-05-22T10:03:11+00:00"
  }
]
```

### `GET /v1/sessions/:agent_id/:session_id`
Chronological `AgentTraceEvent[]` for one session.

### `GET /v1/reflections`
Lists Hermes-generated reflection notes (newest first). Generation
stays Hermes's job; the sidecar only serves what is on disk.

```json
[ { "name": "reflection-2026-05-22.md", "date": "2026-05-22" } ]
```

### `GET /v1/reflections/:name`
One reflection note. `name` must be a bare `reflection-*.md` file name
(path-traversal is rejected with `400`).

```json
{ "name": "reflection-2026-05-22.md", "date": "2026-05-22", "content": "---\n..." }
```

## Compatibility

| Change | Impact |
|---|---|
| Add a new `event_type` value | Minor — old consumers will accept it via passthrough on `payload` but won't recognise the literal in `event_type` enums; bump SDKs together. |
| Add a key to `payload` | Backward compatible by design (payload is `dict[str, Any]`). |
| Add a top-level field | Breaking — both SDKs use strict envelope validation (`extra="forbid"` / Zod `.strict()`). Coordinate releases. |
| Change `metrics` field type | Breaking — metrics is `passthrough` but typed; rename the field instead of repurposing it. |
