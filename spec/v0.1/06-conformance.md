# 6. Conformance

**Status:** Normative.

This section defines what an implementation MUST demonstrate to claim
"TrustLayer v0.1 compliant." Claims are made per **surface** — an
implementation MAY claim conformance on the wire format and policy
language without implementing the HTTP API, and vice versa.

## 6.1 Surfaces

The protocol has three surfaces a third party may implement:

1. **Wire-format conformance** — the implementation can parse and
   produce `AgentTraceEvent` envelopes per [§1](./01-wire-format.md)
   and [§2](./02-event-types.md).
2. **Policy-engine conformance** — the implementation can evaluate
   any v0.1 policy per [§4](./04-policy-language.md).
3. **HTTP API conformance** — the implementation hosts the v0.1
   HTTP API per [§5](./05-http-api.md).

Claiming a higher-numbered surface does not imply conformance with
lower-numbered ones, but a useful sidecar will typically claim all
three.

## 6.2 Wire-format conformance

An implementation claiming this surface MUST:

- **W1.** Reject any `AgentTraceEvent` carrying an unknown top-level
  field (§1.2).
- **W2.** Accept and round-trip an event whose only present fields
  are `trace_id`, `agent_id`, `session_id`, `timestamp`, and
  `event_type` (§1.3). The deserialised value MUST have
  `cynefin_domain` equal to `DISORDER` and `payload`, `metrics` each
  equal to `{}`.
- **W3.** Accept timestamps in both the `+HH:MM` and `Z` forms and
  reject timestamps without an offset (§1.3 `timestamp`).
- **W4.** Encode and decode the `event_type`, `cynefin_domain`, and
  `Decision` enums in `SCREAMING_SNAKE_CASE` exactly.
- **W5.** Treat the seven event types defined in §2 as the v0.1 set
  and preserve unknown values on receipt (§2.8).
- **W6.** Preserve unknown keys inside `payload` and `metrics`
  through serialise / deserialise cycles (§1.4, §1.5).
- **W7.** Generate `trace_id` values as fresh UUID v4s when emitting
  events.

## 6.3 Policy-engine conformance

An implementation claiming this surface MUST:

- **P1.** Parse the `Policy` JSON document of §4.1, rejecting any
  invalid `Decision` value.
- **P2.** Evaluate rules in declaration order and return the first
  match (§4.4).
- **P3.** Implement `MatchSpec.event_type`, `tool_name`, `agent_id`,
  and `cynefin_domain` predicates with equality semantics (§4.2).
- **P4.** Implement `MatchSpec.payload` predicates per §4.3 in full:
  dotted-path resolution, array indexing on numeric segments, deep
  equality on values, missing-path = no match, `null` literal
  matches `null` value only, no type coercion, AND across keys.
- **P5.** Produce the `Verdict` shape of §5.2 (`decision`, `rule`,
  `reason`, `policy`) when adjudicating an event.
- **P6.** Apply the default-verdict rules of §4.5, including the
  `CHAOTIC`-domain `ESCALATE` default.

## 6.4 HTTP API conformance

An implementation claiming this surface MUST:

- **H1.** Expose the routes listed as REQUIRED in §5.1.
- **H2.** Accept both single-event and batch shapes on
  `POST /v1/events` (§5.3).
- **H3.** Deduplicate events on `trace_id` in the trace store and
  reflect that in the `stored` count (§5.3).
- **H4.** Honor every documented query parameter on
  `GET /v1/events` (§5.3).
- **H5.** Return chronological event arrays from `GET /v1/events`
  and `GET /v1/sessions/{agent_id}/{session_id}` (§5.3, §5.4).
- **H6.** Make `GET /healthz` reachable without authentication, even
  when the bearer-token gate is active (§5.5, §5.8).

An implementation claiming HTTP-API conformance MAY additionally
implement any combination of:

- The reflection routes of §5.6.
- The metrics route of §5.7.
- The bearer-token gate of §5.8.
- The ingest rate limit of §5.9.
- Permissive CORS per §5.10.

These OPTIONAL surfaces, when implemented, MUST follow their
respective normative requirements; they are conformance-affecting
only in that an implementation cannot half-implement them.

## 6.5 Claiming conformance

Conformance is self-declared. An implementation MAY publish a
statement of the form:

> "<implementation name> v<version> is **TrustLayer v0.1 compliant**:
> wire-format, policy-engine, HTTP API."

A claim that omits one or more surfaces MUST list which surfaces
ARE claimed.

A language-agnostic fixture set is a documented follow-up (ADR-010).
Until that ships, conformance is established by reviewing the
implementation against this document; the reference Rust + Python +
TypeScript test suites (`core-rs/tests/cross_language.rs`,
`sdks/python/tests/`, `sdks/typescript/tests/`) provide a starting
point.

## 6.6 Out of scope (informative)

The following are NOT requirements of v0.1 conformance:

- A specific transport for the MCP server.
- A specific persistence backend for the trace store.
- A specific reflector for the recursive-memory layer.
- Any particular operational tooling (dashboards, log shippers).
- A specific authentication mechanism beyond the shared-token
  contract of §5.8 (mTLS, OAuth2, etc. are out of scope).
