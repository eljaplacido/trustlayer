# 5. HTTP API

**Status:** Normative.

This section defines the HTTP surface that the TrustLayer sidecar
exposes. A conforming implementation MUST implement all routes
listed in §5.1; routes in §5.5–§5.7 are optional operational
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

The response body is a chronological JSON array of `AgentTraceEvent`.
"Chronological" means ordered by `timestamp` ascending; ties MAY be
broken by insertion order.

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
