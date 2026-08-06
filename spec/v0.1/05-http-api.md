# 5. HTTP API

**Status:** Normative.

This section defines the HTTP surface that the TrustLayer sidecar
exposes. A conforming implementation MUST implement all routes
listed in §5.1; routes in §5.5–§5.7 and §5.12 are optional
surfaces and conformance is described per route.

All request and response bodies MUST be encoded as UTF-8 JSON.
Implementations MUST set `Content-Type: application/json` on every
JSON response unless a route specifies otherwise (e.g. `/metrics`).

## 5.1 Required routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/check` | Adjudicate one event against a policy. §5.2 |
| `POST` | `/v1/events` | Ingest events into the trace store. §5.3 |
| `GET`  | `/v1/events` | List stored events with optional filters. §5.3 |
| `GET`  | `/v1/sessions` | List per-`(agent_id, session_id)` summaries. §5.4 |
| `GET`  | `/v1/sessions/{agent_id}/{session_id}` | List the events of one session. §5.4 |
| `GET`  | `/healthz` | Liveness signal. §5.5 |

Optional surfaces: reflections (§5.6), metrics (§5.7), and the
evidence-integrity routes (§5.12) that back an Art. 12 tamper-evidence
claim.

## 5.2 `POST /v1/check`

**Request body**

```json
{
  "event":       { /* AgentTraceEvent (§1) */ },
  "policy_name": "string | null"
}
```

- `event` — REQUIRED. A full `AgentTraceEvent` envelope (§1).
- `policy_name` — OPTIONAL. Reserved for multi-policy support; a
  conforming v0.1 implementation MAY accept and ignore this field.
  Receivers that do not implement multi-policy MUST behave identically
  whether the field is present or absent.

**Response — 200**

```json
{
  "decision": "PASS | FAIL | ESCALATE",
  "rule":     "string | null",
  "reason":   "string | null",
  "policy":   "string"
}
```

- `decision` — REQUIRED. Shares its enum domain with
  `POLICY_CHECK.payload.result` (§2.5).
- `rule` — REQUIRED, `null` when no rule matched and the default
  fired.
- `reason` — REQUIRED, `null` for the `PASS`-by-default branch.
  Populated for matching rules carrying a reason, and for the
  `CHAOTIC` Cynefin default (§4.5).
- `policy` — REQUIRED. The policy's `name`.

The handler MUST be **stateless** with respect to events: a call to
`/v1/check` MUST NOT mutate the trace store. Persistence is the
caller's responsibility (via `POST /v1/events` if desired).

## 5.3 Trace store routes

### `POST /v1/events`

**Request body**

The body MUST be either a single `AgentTraceEvent` object or a JSON
array of `AgentTraceEvent` objects. Receivers MUST accept both
shapes. (This matches what `TrustLayerClient.emit` / `emit_batch`
emit in the reference SDKs.)

**Response — 200**

```json
{ "stored": <integer> }
```

- `stored` — REQUIRED. Count of newly-stored events. Receivers MUST
  deduplicate on `trace_id` (§1.3) so a duplicate event in the batch
  is not double-counted.

### `GET /v1/events`

Query parameters, all OPTIONAL:

| Param | Type | Effect |
|---|---|---|
| `agent_id` | string | Filter to events with this `agent_id`. |
| `session_id` | string | Filter to events with this `session_id`. |
| `event_type` | `EventType` | Filter to events of this type. |
| `limit` | non-negative integer | Return at most the N most recent events. |
| `after_seq` | non-negative integer | Return only events after this chain position (§5.12). |

The response body is a chronological JSON array of `AgentTraceEvent`.
"Chronological" means ordered by `timestamp` ascending; ties MAY be
broken by insertion order.

`after_seq` requires `agent_id`: chain positions are scoped per agent
(§5.12), so a cursor without an agent names no position. An
implementation that receives `after_seq` without `agent_id` MUST
respond `400`. An implementation that maintains no chain MUST reject
`after_seq` rather than ignore it — silently returning an unfiltered
list would make a paging consumer skip events without knowing it.

The response shape does **not** change when `after_seq` is supplied.
Chain metadata is served from `GET /v1/events/chained` (§5.12) so no
route returns two different body shapes.

## 5.4 Session routes

### `GET /v1/sessions`

The response is a JSON array of session summaries, most-recent-
session first:

```json
[
  {
    "agent_id":    "string",
    "session_id":  "string",
    "event_count": <integer>,
    "first_seen":  "<ISO 8601 with offset>",
    "last_seen":   "<ISO 8601 with offset>"
  }
]
```

All fields REQUIRED.

### `GET /v1/sessions/{agent_id}/{session_id}`

The response is a chronological JSON array of `AgentTraceEvent`
matching the path parameters. Both path parameters MUST be percent-
encoded per [RFC 3986](https://www.rfc-editor.org/rfc/rfc3986).

## 5.5 `GET /healthz`

A liveness signal. The response body MUST be `"ok"` (the literal
three-byte string, with or without a quoting wrapper depending on
content type — implementations MAY return `text/plain`). The route
MUST be reachable without authentication even when the bearer-token
gate (§5.8) is configured.

## 5.6 Hermes reflection routes (OPTIONAL)

Implementations MAY expose the following routes to serve the Hermes
recursive-memory subagent's reflection output. They are not
required for v0.1 conformance.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/reflections` | List `{name, date}` of reflection notes. |
| `GET` | `/v1/reflections/{name}` | Return one reflection by name. |

When implemented:

- `/v1/reflections/{name}` MUST reject names that fail a path-traversal
  check (anything that is not a bare `reflection-*.md` filename) with
  `400 Bad Request`.
- Implementations MUST NOT generate reflections in response to these
  routes; they are read-only views over what the recursive-memory
  layer has already produced. Generation is out of band.

## 5.7 Metrics (OPTIONAL)

Implementations MAY expose `GET /metrics` returning a Prometheus
text-format exposition (per
[OpenMetrics](https://openmetrics.io/) and the Prometheus
[`text/plain; version=0.0.4`](https://github.com/prometheus/docs/blob/main/content/docs/instrumenting/exposition_formats.md)
content type). When implemented, the route:

- MUST be reachable without authentication even when the bearer-token
  gate (§5.8) is configured.
- MUST expose at least counters for ingest volume and verdict
  decisions; the exact metric names are not normative.

## 5.8 Authentication (OPTIONAL but RECOMMENDED)

Implementations MAY require a shared bearer token on every route
except `/healthz` and `/metrics`. When the token gate is enabled:

- Receivers MUST require an `Authorization: Bearer <token>` header on
  every protected request.
- Comparisons MUST be constant-time to avoid timing-oracle leaks.
- On a missing, malformed, or wrong header, the server MUST respond
  `401 Unauthorized` with `WWW-Authenticate: Bearer realm="<realm>"`
  and an empty body.

When the gate is disabled (the default), receivers MUST behave as if
the gate did not exist. They MUST NOT silently accept a wrong token
or partial credentials.

## 5.9 Rate limiting (OPTIONAL)

Implementations MAY rate-limit `POST /v1/events` to protect the
trace store. When rate-limiting is active and the limit is exceeded:

- The server MUST respond `429 Too Many Requests`.
- The response MUST include a `Retry-After` header containing a
  non-negative integer number of seconds.
- The body MAY be human-readable text.

Other routes — including `GET /v1/events` — MUST NOT share the
ingest limiter.

## 5.10 CORS (informative)

Implementations MAY enable permissive CORS so that browser-based
dashboards can read the trace store from a different origin. The
reference Rust sidecar does so. Permissive CORS is **not** required
for conformance.

## 5.11 OpenTelemetry interop (informative)

Implementations MAY bridge `AgentTraceEvent`s into an OpenTelemetry
pipeline. The reference Python SDK ships such a bridge (ADR-012)
that maps each event to one OTel span using the caller's
`TracerProvider`. The attribute naming convention is:

- `trustlayer.trace_id`, `trustlayer.agent_id`, `trustlayer.session_id`,
  `trustlayer.event_type`, `trustlayer.cynefin_domain` for the
  envelope.
- `trustlayer.payload.<dotted-path>` for payload fields (same dotted-
  path convention as §4.3 payload predicates).
- `trustlayer.metrics.<key>` for metrics fields.

Cross-language ports of the same bridge are encouraged to use the
same prefixes so dashboards stay portable across SDKs. Bridges are
**not** part of conformance — an implementation may ship one or not.


## 5.12 Evidence integrity routes (OPTIONAL)

**Status:** Normative for implementations that claim Art. 12
tamper-evidence. An implementation MAY omit this section entirely; one
that omits it MUST NOT claim tamper-evident logging.

EU AI Act Art. 12 requires high-risk AI systems to keep automatic logs
over their lifetime. A log an operator can silently edit does not
satisfy that, so an implementation MAY maintain a hash chain over
stored events and expose it here. The design rationale is
[ADR-017](../../obsidian_vault/01_Architecture/ADR-017-Evidence-Integrity-Hash-Chain-Retention.md).

These routes are additive and therefore MINOR per §1.7. Nothing in this
section changes the `AgentTraceEvent` envelope (§1.2): a client cannot
know its position in the log, so chain state is computed **by the store
on append** and never appears in an event.

### 5.12.1 Chain model

Each `agent_id` has an independent chain. Positions (`seq`) are 1-based
and contiguous **within one agent**; two agents both start at 1.
Per-agent scoping is required, not incidental — evidence is assessed
per AI system, and verifying system X must not require disclosing
system Y's events.

Each position carries:

| Field | Type | Meaning |
|---|---|---|
| `seq` | integer ≥ 1 | Position in this agent's chain. |
| `prev_hash` | 64 hex chars | Hash at `seq - 1`; 64 zeros at `seq = 1`. |
| `hash` | 64 hex chars | SHA-256 over the preimage below. |
| `recorded_at` | RFC 3339 | When the **store** observed the event. |

`recorded_at` MUST be the store's clock, never the event's
`timestamp`. A client clock is attacker-controlled and skewed across a
fleet; the store can only honestly attest to when it saw the event.

The hash preimage is the compact JSON object with lexicographically
ordered keys:

```json
{"agent_id":"…","event":{…},"prev_hash":"…","recorded_at":"…","seq":N,"trace_id":"…"}
```

`event` is the complete `AgentTraceEvent` serialised canonically:
compact separators (`,` and `:`, no spaces) and object keys in
lexicographic order at every level. Building an object rather than
concatenating fields is required so no `agent_id` can be crafted to
impersonate another `(seq, hash)` pair by smuggling a separator.

### 5.12.2 `GET /v1/events/chained`

| Param | Type | Required | Effect |
|---|---|---|---|
| `agent_id` | string | **yes** | Chain to page. |
| `after_seq` | integer | no | Return positions strictly greater than this. |
| `limit` | integer | no | Return at most N entries. |

```json
{
  "agent_id": "checkout-assistant",
  "events": [
    { "seq": 41, "hash": "…", "recorded_at": "2026-08-05T09:00:00Z",
      "event": { "trace_id": "…", "…": "…" } }
  ],
  "next_after_seq": 41,
  "head_seq": 900,
  "archived_in_range": 0
}
```

Entries MUST be ordered by `seq` ascending. `next_after_seq` is the
cursor for the next page and MUST be `null` once the end of the chain
is reached. Paging by chain position rather than offset is required:
an offset cursor over a log that is being appended to, or compacted by
retention, silently skips or repeats events.

`archived_in_range` counts positions whose event is no longer in the
live log because retention moved it to archive storage. Implementations
MUST report such positions rather than omit them silently — a page with
an unreported hole reads as a complete history.

### 5.12.3 `GET /v1/integrity/verify`

| Param | Type | Required | Effect |
|---|---|---|---|
| `agent_id` | string | no | Verify only this agent's chain. |

```json
{
  "ok": true,
  "chains": [
    { "agent_id": "checkout-assistant", "entries_checked": 900,
      "verified_through_seq": 900, "first_bad_seq": null, "reason": null }
  ]
}
```

`ok` MUST be true only when every reported chain verified.
`verified_through_seq` is the last position that verified;
`first_bad_seq` is the first that did not, with a human-readable
`reason`.

A tampered log MUST be reported with HTTP `200` and `"ok": false`. The
request succeeded; its answer is that the log is broken. Returning an
error status would let a client's retry logic mistake tampering for a
transient fault.

An agent with no chain MUST be absent from `chains` rather than
reported as verified — an unknown `agent_id` (a typo, say) must never
read as a clean bill of health.

### 5.12.4 `GET /v1/integrity/checkpoints`

| Param | Type | Required | Effect |
|---|---|---|---|
| `agent_id` | string | no | Only this agent's checkpoints. |

A checkpoint commits to a chain head at a point in time. Because the
head hash commits to every prior position, one checkpoint pins the
whole prefix.

```json
{
  "checkpoints": [
    { "agent_id": "checkout-assistant", "seq": 1000, "head_hash": "…",
      "created_at": "2026-08-05T09:00:00Z",
      "public_key": "…", "signature": "…" }
  ],
  "verified_signatures": 1,
  "invalid_signatures": 0
}
```

`public_key` and `signature` are lowercase hex and MUST be omitted when
a checkpoint is unsigned. Signatures, when present, MUST be Ed25519
over the compact, key-ordered JSON object:

```json
{"agent_id":"…","created_at":"…","head_hash":"…","seq":N}
```

This preimage is normative so an auditor can verify a checkpoint with
any Ed25519 implementation, without running this software.

`invalid_signatures` counts checkpoints that claim a signature which
does not verify. Any non-zero value is a finding.

Implementations MUST NOT present `verified_signatures` as proof of
authenticity. The key travels in the same response as the signature, so
verifying one against the other proves only internal consistency; an
auditor MUST compare the key against one received out of band.

### 5.12.5 Status codes

| Situation | Status |
|---|---|
| Chain served, whatever it says | `200` |
| `after_seq` without `agent_id`, or `/v1/events/chained` without `agent_id` | `400` |
| Backend maintains no chain | `501` |

`501` rather than `500` is required: the request was well-formed and
the server is healthy, it simply cannot make the attestation asked of
it. A `500` reads as a transient fault an evidence consumer should
retry, when in fact the deployment must be reconfigured.

### 5.12.6 What these routes do and do not prove

Stated normatively because an implementation that overstates this is
worse than one that omits the section.

These routes prove the log has **not been altered since the store
recorded it**. They do not prove:

- that the emitting agent told the truth — attestation of the emitter
  is out of scope;
- that events which *should* have been recorded were recorded — an
  event never submitted is invisible to every mechanism here;
- authenticity of a checkpoint, unless its public key was obtained out
  of band.
