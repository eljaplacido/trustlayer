# 1. Wire Format

**Status:** Normative.

Every event observed in the TrustLayer protocol travels as a single
**`AgentTraceEvent`** JSON object. This section defines the envelope,
its required and optional fields, and the JSON encoding rules.

## 1.1 Encoding

- An `AgentTraceEvent` MUST be encoded as a JSON object per
  [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259).
- Implementations MUST use UTF-8 encoding for the JSON bytes on the
  wire.
- Implementations MUST reject (treat as a protocol error) any
  `AgentTraceEvent` JSON whose top-level shape is not an object.

## 1.2 Strict envelope

The envelope is closed: no fields beyond those defined in this section
are permitted at the top level of `AgentTraceEvent`.

- Implementations MUST reject any `AgentTraceEvent` carrying an
  unknown top-level field.
- The `payload` and `metrics` sub-objects are NOT subject to this
  restriction (see §1.4 and §1.5).

The reference implementations enforce this with Pydantic
`extra="forbid"`, Zod `.strict()`, and serde `deny_unknown_fields`.

## 1.3 Envelope fields

```json
{
  "trace_id":       "<UUID v4>",
  "agent_id":       "<string>",
  "session_id":     "<string>",
  "timestamp":      "<ISO 8601 with offset>",
  "event_type":     "<EventType>",
  "cynefin_domain": "<CynefinDomain, default DISORDER>",
  "payload":        { /* event-specific, see §2 */ },
  "metrics":        { /* see §1.5 */ }
}
```

### `trace_id` — REQUIRED

- A [UUID v4](https://www.rfc-editor.org/rfc/rfc4122) identifying the
  event uniquely.
- Implementations MUST generate a new `trace_id` for each emitted
  event.
- Persistence layers MUST deduplicate on `trace_id`: an event seen a
  second time with the same `trace_id` MUST NOT be appended again.

### `agent_id` — REQUIRED

- A non-empty string naming the agent that emitted the event.
- Format is opaque to the protocol; implementations MAY treat it as a
  human-readable identifier, MAY treat it as a stable ID assigned by
  an orchestrator, or MAY treat it as both.

### `session_id` — REQUIRED

- A non-empty string identifying the agent's execution session.
- The pair `(agent_id, session_id)` MUST be sufficient to group all
  events of one logical agent run.

### `timestamp` — REQUIRED

- An [ISO 8601](https://www.iso.org/iso-8601-date-and-time-format.html)
  date-time **with a UTC offset** (`±HH:MM` or `Z`).
- Implementations MUST NOT emit a timestamp without an offset.
- Receivers MUST accept both the `+00:00` and `Z` forms.

### `event_type` — REQUIRED

- One of the seven values defined in [§2](./02-event-types.md):
  `AGENT_START`, `TOOL_CALL`, `TOOL_RESULT`, `LLM_CALL`,
  `POLICY_CHECK`, `HUMAN_ESCALATION`, `AGENT_END`.
- Values MUST be encoded in `SCREAMING_SNAKE_CASE`.

### `cynefin_domain` — OPTIONAL (default `DISORDER`)

- One of the five values defined in [§3](./03-cynefin.md): `CLEAR`,
  `COMPLICATED`, `COMPLEX`, `CHAOTIC`, `DISORDER`.
- If absent, implementations MUST behave as if the value were
  `DISORDER`.
- Values MUST be encoded in `SCREAMING_SNAKE_CASE`.

### `payload` — OPTIONAL (default `{}`)

- A JSON object whose contents are determined by `event_type`. See
  [§2](./02-event-types.md) for per-type contracts.
- Implementations MUST accept arbitrary nested JSON values inside
  `payload`. Unknown payload keys MUST NOT be rejected by the
  envelope validator (policy engines MAY make their own decisions
  on unknown payload keys; see [§4](./04-policy-language.md)).

### `metrics` — OPTIONAL (default `{}`)

See §1.5.

## 1.4 `payload` extension

`payload` is intentionally open-ended so that new tool / LLM /
event-specific data can be added without bumping the wire-format
version. The per-`event_type` contracts in [§2](./02-event-types.md)
list keys that implementations MUST emit when applicable and keys that
implementations SHOULD recognize. Additional keys MAY appear and
implementations MUST preserve them through round-trips.

## 1.5 `metrics` object

```json
{
  "latency_ms":         123.4,
  "cost_usd":           0.0123,
  "tokens_prompt":      150,
  "tokens_completion":  45
}
```

- All four well-known metric keys are OPTIONAL.
- `latency_ms` and `cost_usd` MUST be JSON numbers (integer or float)
  when present.
- `tokens_prompt` and `tokens_completion` MUST be non-negative JSON
  integers when present.
- Additional keys MAY appear; implementations MUST preserve them
  through round-trips. Receivers MAY ignore keys they do not
  understand.

## 1.6 JSON examples (informative)

A minimal valid event:

```json
{
  "trace_id": "11111111-1111-4111-8111-111111111111",
  "agent_id": "researcher-1",
  "session_id": "S1",
  "timestamp": "2026-05-07T09:00:01+00:00",
  "event_type": "AGENT_START"
}
```

A tool call with metrics and a Cynefin classification:

```json
{
  "trace_id": "22222222-2222-4222-8222-222222222222",
  "agent_id": "researcher-1",
  "session_id": "S1",
  "timestamp": "2026-05-07T09:00:02+00:00",
  "event_type": "TOOL_CALL",
  "cynefin_domain": "COMPLEX",
  "payload": {
    "tool_name": "external_llm",
    "tool_args": { "prompt": "summarise this report" },
    "model": "gpt-4"
  },
  "metrics": {
    "latency_ms": 412.0,
    "cost_usd":   0.0015,
    "tokens_prompt": 150,
    "tokens_completion": 45
  }
}
```

## 1.7 Compatibility rules

The following rules govern wire-format changes within a major version.
The authoritative version policy lives in
[`docs/VERSIONING.md`](../../docs/VERSIONING.md).

| Change | Class |
|---|---|
| Add an OPTIONAL field to the envelope | MINOR |
| Add a key to `metrics` | MINOR |
| Add an `event_type` value | MINOR |
| Add a `CynefinDomain` value | MINOR |
| Add a new HTTP route in §5 | MINOR |
| Add an OPTIONAL field to a `MatchSpec` (§4) | MINOR |
| Remove or rename any field, type, or enum value | MAJOR |
| Change the type of an existing field | MAJOR |
| Tighten validation so existing valid payloads are rejected | MAJOR |
