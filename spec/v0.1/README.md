---
spec: TrustLayer Protocol
version: 0.1
status: Active
released: 2026-05-25
schema_version: 0.1
license: Apache-2.0
---

# TrustLayer Protocol — Version 0.1

This is the formal specification of the TrustLayer protocol at version
**0.1**. It defines the wire format, event types, policy language, and
HTTP API that any conforming implementation MUST satisfy.

This document and the documents it indexes use the keywords **MUST**,
**MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**,
**SHOULD NOT**, **RECOMMENDED**, **MAY**, and **OPTIONAL** as described
in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174) when, and only
when, they appear in all capitals.

## Section index

1. [Wire format](./01-wire-format.md) — `AgentTraceEvent` envelope,
   types, and JSON encoding.
2. [Event types](./02-event-types.md) — the seven `event_type` values
   and their payload contracts.
3. [Cynefin domain](./03-cynefin.md) — the `CynefinDomain` enum and its
   semantic role in policy evaluation.
4. [Policy language (CSL)](./04-policy-language.md) — `Policy`,
   `PolicyRule`, `MatchSpec`, dotted-path payload predicates,
   evaluator behaviour, default verdict rules.
5. [HTTP API](./05-http-api.md) — guardian + trace-store endpoints,
   bearer-token authentication, request and response shapes,
   `/metrics`, ingest rate-limit, `/healthz`.
6. [Conformance](./06-conformance.md) — what an implementation MUST
   demonstrate to claim "TrustLayer v0.1 compliant."

## Status of this specification

This is a **stable** version. The directory `spec/v0.1/` will not be
edited except for editorial fixes (typos, broken links). New
capabilities go into a `spec/v0.2/`, `spec/v1.0/`, etc., per the
versioning policy.

The current reference implementations are:

| Language / Surface | Project | Notes |
|---|---|---|
| Rust | `core-rs/` | Schema mirror, policy engine, HTTP sidecar. |
| Python | `sdks/python/` | Tracer + guardian client. |
| TypeScript | `sdks/typescript/` | Tracer + guardian client. |
| MCP (Python) | `mcp-server/` | Exposes the SDK + guardian + Hermes over MCP. |

## Change log (editorial only)

| Date | Change | Author |
|---|---|---|
| 2026-05-25 | Initial publication of v0.1. | TrustLayer Contributors |
