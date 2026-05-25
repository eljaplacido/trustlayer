# 2. Event Types

**Status:** Normative.

The `event_type` field selects which payload contract applies. This
section defines the seven event types and the payload keys an
implementation MUST emit when applicable, plus the keys it SHOULD
recognize on the receive side.

The full `event_type` enum:

| Value | Section |
|---|---|
| `AGENT_START` | [§2.1](#21-agent_start) |
| `TOOL_CALL` | [§2.2](#22-tool_call) |
| `TOOL_RESULT` | [§2.3](#23-tool_result) |
| `LLM_CALL` | [§2.4](#24-llm_call) |
| `POLICY_CHECK` | [§2.5](#25-policy_check) |
| `HUMAN_ESCALATION` | [§2.6](#26-human_escalation) |
| `AGENT_END` | [§2.7](#27-agent_end) |

All values MUST be encoded in `SCREAMING_SNAKE_CASE` (§1.3).

The `payload` shapes below are **contracts**, not closed schemas:
implementations MUST emit listed keys when the information is
available, SHOULD recognize listed keys on receipt, and MAY include
additional keys (§1.4).

---

## 2.1 `AGENT_START`

Emitted once at the start of an agent's session.

```json
"payload": {
  "goal": "string"
}
```

- `goal` — RECOMMENDED. A human-readable summary of what the agent is
  trying to accomplish in this session.

## 2.2 `TOOL_CALL`

Emitted when the agent invokes a tool. Pairs with a subsequent
`TOOL_RESULT` carrying the same `trace_id` MUST NOT be assumed —
implementations MAY emit `TOOL_RESULT` with a different `trace_id`
and correlate by `session_id` and ordering.

```json
"payload": {
  "tool_name": "string",
  "tool_args": { /* arbitrary */ },
  "model":     "string"
}
```

- `tool_name` — REQUIRED. Stable identifier of the invoked tool.
- `tool_args` — RECOMMENDED. Free-form arguments passed to the tool.
- `model` — OPTIONAL. The model name when the tool itself is a model
  call. Allows policy rules to match on
  `payload.model` (see [§4.3](./04-policy-language.md#43-payload-predicates)).

## 2.3 `TOOL_RESULT`

Emitted when a tool returns.

```json
"payload": {
  "tool_name": "string",
  "result":    "<arbitrary>",
  "error":     "string | null"
}
```

- `tool_name` — REQUIRED.
- `result` — RECOMMENDED on success. MAY be any JSON value.
- `error` — RECOMMENDED on failure. A short, human-readable message.

## 2.4 `LLM_CALL`

Emitted for any LLM invocation that the agent itself drives (as
opposed to a tool that happens to wrap a model — that is `TOOL_CALL`).

```json
"payload": {
  "model":    "string",
  "prompt":   "string",
  "response": "string"
}
```

- `model` — REQUIRED.
- `prompt` — RECOMMENDED. The prompt as sent to the model. Receivers
  MUST treat this as privacy-sensitive (see §5 on trace-store auth).
- `response` — RECOMMENDED. Receivers MUST treat this as
  privacy-sensitive.

## 2.5 `POLICY_CHECK`

Emitted by the `Tracer.check()` helper after a guardian decision, so
the trace stream itself records the verdict and not only the response
to `/v1/check`.

```json
"payload": {
  "policy_name": "string",
  "action":      "string",
  "result":      "PASS | FAIL | ESCALATE",
  "reason":      "string | null"
}
```

- `policy_name` — REQUIRED. The policy that produced the verdict.
- `action` — REQUIRED. A short label describing what was checked
  (typically the tool name being evaluated).
- `result` — REQUIRED. MUST be one of `PASS`, `FAIL`, `ESCALATE`.
  Shares its enum domain with the guardian verdict (§5.2).
- `reason` — OPTIONAL. Populated when the matching rule (or the
  Cynefin default in §3) carries a reason.

## 2.6 `HUMAN_ESCALATION`

Emitted when the agent stops and hands control to a human (e.g. after
an `ESCALATE` verdict, or unilaterally on its own judgement).

```json
"payload": {
  "reason":  "string",
  "context": { /* arbitrary */ }
}
```

- `reason` — REQUIRED.
- `context` — OPTIONAL. Free-form information for the human reviewer.

## 2.7 `AGENT_END`

Emitted once at the end of a session.

```json
"payload": {
  "status":  "completed | failed | aborted | <other string>",
  "summary": "string"
}
```

- `status` — RECOMMENDED. Implementations SHOULD use one of
  `completed`, `failed`, `aborted` when possible, but MAY use other
  strings.
- `summary` — OPTIONAL.

---

## 2.8 Forward compatibility (informative)

A future `MINOR` may add new `event_type` values. Receivers that do
not recognize a value MUST treat the envelope as valid and SHOULD
pass the event through any persistence or routing layer unchanged.
Implementations MAY surface a warning but MUST NOT reject the event.
