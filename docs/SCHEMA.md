# TrustLayer Event Schema

> **The citable, normative spec lives at
> [`spec/v0.1/`](../spec/v0.1/README.md).** This document is the
> implementation-mirror view of the same wire format —
> developer-friendly, evolves with the SDK code. When the two disagree,
> the spec is authoritative.

**`SCHEMA_VERSION = 0.1`** — see [`docs/VERSIONING.md`](./VERSIONING.md)
and the normative spec at [`spec/v0.1/`](../spec/v0.1/README.md).

TrustLayer uses an OpenTelemetry-inspired schema for tracking agentic
execution. Both SDKs serialise to the same shape, and the Rust core
(Phase 4) plus Hermes (Phase 3) consume it without re-deriving types.

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
  "event_type": "AGENT_START | TOOL_CALL | TOOL_RESULT | LLM_CALL | POLICY_CHECK | HUMAN_ESCALATION | AGENT_END | DISCLOSURE_SHOWN | CONTENT_MARKED | HUMAN_DECISION | HARNESS_SNAPSHOT",
  "parent_trace_id": "uuid-v4",   // optional — causal parent; omitted when unset
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
- `parent_trace_id` is **optional** and names the event that *caused* this
  one. Only the agent knows which call spawned which, so emitters carry it
  explicitly or not at all — inferring it from arrival order breaks under
  concurrency, which is the regime agentic systems run in. **Absent means
  unknown, never "no parent"**: derived metrics report `unknown` rather
  than assuming a flat structure. A spawned sub-agent's `AGENT_START`
  should carry the `trace_id` of the `TOOL_CALL` that spawned it, which is
  what makes cross-agent delegation depth computable. It is omitted from
  the wire entirely when unset, so v0.1 emitters produce byte-identical
  output.
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

### `DISCLOSURE_SHOWN`
Emitted when an EU AI Act Art. 50 transparency disclosure is presented
to a natural person — at the point the notice is shown, not when it is
configured.
```json
{
  "disclosure_type": "ai_interaction | emotion_recognition | biometric_classification | ai_generated | deepfake | public_interest_text",
  "user_notice": "string",  // the disclosure text as shown
  "surface": "string",      // optional — e.g. "chat_header", "pre_response"
  "locale": "string"        // optional — BCP 47 tag
}
```
`disclosure_type` maps to Art. 50 as: `ai_interaction` → 50(1);
`emotion_recognition` / `biometric_classification` → 50(3) (the Act's
term for the latter is "biometric categorisation"); `ai_generated` →
50(2); `deepfake` / `public_interest_text` → 50(4). Other strings are
permitted. The event records that a disclosure occurred, not that it
was adequate.

### `CONTENT_MARKED`
Emitted when synthetic content is marked as artificially generated or
manipulated, per Art. 50(2). One event per marked artifact.
```json
{
  "marking_type": "watermark | c2pa | metadata | provenance_manifest",
  "content_type": "text | image | audio | video",
  "artifact_hash": "string",  // optional — enables later re-verification
  "confidence": 0.97,         // optional — number in [0, 1]
  "verification": {           // optional — present only if re-read and confirmed
    "method": "c2pa | watermark | metadata | none",
    "verified": true,
    "verified_at": "<ISO 8601 with offset>",
    "verifier": "string"
  }
}
```
Without a `verification` object this event records a **claim** that the
content was marked. Receivers must not treat the claim as confirmation
that a marking is present in the artifact.

### `HUMAN_DECISION`
The **outcome** of a human escalation, closing the Art. 14 loop.
`HUMAN_ESCALATION` says a human was asked; nothing in v0.1 said what they
answered. An escalation nobody acted on is worse evidence than none — it
shows the mechanism exists and is ignored.
```json
{
  "escalation_trace_id": "<uuid>",     // required — the escalation this resolves
  "decision": "APPROVE | REJECT | MODIFY",
  "reviewer_id": "string",             // required — Art. 14(4) identified person
  "rationale": "string",               // recommended
  "modified_args": {}                  // optional, when decision == MODIFY
}
```
Pair on `escalation_trace_id`, never on ordering — ordering breaks under
concurrency, which is the regime agentic systems operate in. Put the
escalation→decision gap in `metrics.latency_ms`; that is the number Art. 14
effectiveness is measured on. Absence of this event is **not** approval.

### `HARNESS_SNAPSHOT`
Fingerprints the configuration a session ran under, emitted once per
session next to `AGENT_START`. An agent's behaviour is determined as much
by its harness — model bindings, tool inventory, system prompt — as by its
code, and none of that shows up in a conventional change log. Without it,
Art. 43 substantial-modification detection has nothing to diff.
```json
{
  "harness_hash": "sha256:…",          // required
  "model_bindings": [{"role": "planner", "model": "…", "provider": "…", "params_hash": "…"}],
  "tools": [{"name": "…", "version": "…", "trust_tier": "untrusted | internal | privileged",
             "capabilities": ["net.egress"]}],
  "mcp_servers": [{"name": "…", "version": "…", "transport": "stdio"}],
  "prompt_hashes": {"system": "sha256:…"},
  "autonomy": {"max_delegation_depth": 3, "human_in_loop": true},
  "sdk": {"name": "trustlayer-python", "version": "0.1.0"}
}
```
**Prompt hashes, never prompt text.** System prompts are trade secrets and
often contain customer data; a hash proves "this changed" without
disclosing what it says, which is all that change detection needs.

This is not attestation. It records what the emitter says it was
configured with; nothing verifies that against the running process.

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

### `GET /v1/events?agent_id=&session_id=&event_type=&limit=N&after_seq=S`
Every query parameter is optional. `event_type` takes one of the
`event_type` enum values; `limit` returns the most-recent N. Response is
a chronological `AgentTraceEvent[]`.

`after_seq` is a chain cursor (see integrity routes below) and requires
`agent_id`, because chain positions are scoped per agent. Supplying it
without one is a `400`. The response shape is unchanged either way — the
chain metadata lives on its own route rather than reshaping this one.

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

## Evidence-integrity HTTP API (Phase 8, ADR-017)

Optional routes backing an EU AI Act Art. 12 tamper-evidence claim.
Normative definition: [`spec/v0.1/05-http-api.md` §5.12](../spec/v0.1/05-http-api.md).
An implementation that omits them must not claim tamper-evident logging.

**Nothing here changes the `AgentTraceEvent` envelope.** A client cannot
know its position in the log, so chain state is computed by the store on
append and served *alongside* events, never inside them.

Chains are scoped per `agent_id`: positions are 1-based and contiguous
within one agent, and two agents both start at 1. That is the unit an
auditor asks about, and it means verifying system X never requires
disclosing system Y's events.

### `GET /v1/events/chained?agent_id=A&after_seq=S&limit=N`
`agent_id` is required. Pages by chain position, not offset — an offset
cursor over a log being appended to (or compacted by retention) silently
skips events.

```json
{
  "agent_id": "checkout-assistant",
  "events": [
    { "seq": 41, "hash": "…64 hex…", "recorded_at": "2026-08-05T09:00:00+00:00",
      "event": { "trace_id": "…", "…": "…" } }
  ],
  "next_after_seq": 41,
  "head_seq": 900,
  "archived_in_range": 0
}
```

`recorded_at` is the **store's** clock, not the event's `timestamp`: a
client clock is attacker-controlled, so it is the only claim the store
can honestly make. `archived_in_range` counts positions whose event
retention has moved to archive storage — reported, never silently
skipped.

### `GET /v1/integrity/verify?agent_id=A`
Recomputes chains and reports the first divergence in each.

```json
{
  "ok": true,
  "chains": [
    { "agent_id": "checkout-assistant", "entries_checked": 900,
      "verified_through_seq": 900, "first_bad_seq": null, "reason": null }
  ]
}
```

A tampered log is `200` with `"ok": false` — the request succeeded, and
its answer is that the log is broken. An unknown `agent_id` yields an
empty `chains` array, never a vacuous pass.

### `GET /v1/integrity/checkpoints?agent_id=A`
Signed commitments to chain heads. The head hash commits to every prior
position, so one checkpoint pins the whole prefix.

```json
{
  "checkpoints": [
    { "agent_id": "checkout-assistant", "seq": 1000, "head_hash": "…",
      "created_at": "2026-08-05T09:00:00+00:00",
      "public_key": "…64 hex…", "signature": "…128 hex…" }
  ],
  "verified_signatures": 1,
  "invalid_signatures": 0
}
```

`public_key` / `signature` are omitted when unsigned. Signatures are
Ed25519 over `{"agent_id":…,"created_at":…,"head_hash":…,"seq":N}`
(compact, key-ordered) so an auditor can verify with any Ed25519
implementation.

`verified_signatures` is **not** proof of authenticity — the key travels
in the same response as the signature. Compare it against a key received
out of band.

### Status codes
`400` for a cursor without an agent; `501` (not `500`) when the backend
maintains no chain — the server is healthy, it just cannot attest, and a
`500` would read as a retryable fault.

### What this proves
The log has not been altered since the store recorded it. It does **not**
prove the emitting agent told the truth, nor that events which should
have been recorded were — an event never submitted is invisible to all
of it.

## Compatibility

| Change | Impact |
|---|---|
| Add a new `event_type` value | Minor — old consumers will accept it via passthrough on `payload` but won't recognise the literal in `event_type` enums; bump SDKs together. |
| Add a key to `payload` | Backward compatible by design (payload is `dict[str, Any]`). |
| Add a top-level field | Breaking — both SDKs use strict envelope validation (`extra="forbid"` / Zod `.strict()`). Coordinate releases. |
| Change `metrics` field type | Breaking — metrics is `passthrough` but typed; rename the field instead of repurposing it. |
