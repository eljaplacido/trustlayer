---
adr: 011
status: accepted
date: 2026-05-25
tags: [architecture, phase-6, sdk, go, open-standard]
supersedes: []
extends: ["[[ADR-001-SDK-Wedge]]", "[[ADR-010-Formal-Spec-Layout]]"]
---

# ADR-011 — Go SDK (`sdks/go/trustlayer`)

## Context

The v0.1 spec landed in [ADR-010]. The next question every prospective
adopter asks is *which* implementations conform. Today the answer is
"Rust, Python, TypeScript" — which covers a wide slice of the agent
ecosystem but misses a major one: Go.

Go is the language of most of the infra-shaped agent frameworks (LangGraph
Go, eino, the Kubernetes controllers people are wiring agents into, every
serverless platform's Go runtime). An adopter writing a Go agent today
has to either:

- Shell out to the Rust binary / Python SDK as a sidecar, which buys them
  HTTP latency on every event, or
- Write a one-off Go client that drifts from the spec.

The right answer is a first-party Go SDK that mirrors the contract the
Python and TypeScript SDKs already implement, and that the v0.1
conformance section (6.2, 6.3) can be checked off against.

## Decision

Ship `sdks/go/trustlayer/` as a first-party SDK alongside `sdks/python/`
and `sdks/typescript/`. Module path:
`github.com/eljaplacido/trustlayer/sdks/go`. Consumers import the
single `trustlayer` package.

### Layout

```
sdks/go/
├── go.mod
├── go.sum
├── trustlayer/
│   ├── schema.go        AgentTraceEvent, EventType, CynefinDomain, Decision, Metrics.
│   ├── client.go        TrustLayerClient (Emit, EmitBatch). Env-bearer-token fallback.
│   ├── guardian.go      GuardianClient (Check). Fail-open by default.
│   ├── tracer.go        Tracer.ToolCall + Tracer.Check helpers.
│   ├── auth.go          resolveAPIToken() shared by both clients.
│   └── *_test.go        Table-driven tests mirroring the Python coverage.
└── examples/
    └── end_to_end_demo/
        └── main.go      Drives SDK -> Guardian (mock) -> JSONL tee.
```

### Public surface

The Go SDK mirrors the Python contract method-for-method, adjusted for
Go idioms:

| Concept | Python | Go |
|---|---|---|
| Client | `TrustLayerClient(endpoint=..., api_key=...)` | `trustlayer.NewClient(opts ClientOptions)` |
| Emit one | `client.emit(event)` | `client.Emit(ctx, event) error` |
| Emit batch | `client.emit_batch(events)` | `client.EmitBatch(ctx, events) error` |
| Guardian | `GuardianClient(...)` | `trustlayer.NewGuardian(opts GuardianOptions)` |
| Check | `guardian.check(event)` | `guardian.Check(ctx, event) (Verdict, error)` |
| Tracer | `Tracer(...)` | `trustlayer.NewTracer(opts TracerOptions)` |
| Tool span | context-managed `with t.tool_call(...)` | `defer t.ToolCall(ctx, name, args)()` (closure-on-defer pattern) |
| Verdict + emit | `t.check(name, args)` | `t.Check(ctx, name, args) (Verdict, error)` |

The Go API takes a `context.Context` first parameter everywhere — that's
the language idiom and lets callers cancel emits when the agent is
torn down. Instrumentation **MUST** still swallow transport failures
(working agreement 2 from `CLAUDE.md`); errors returned from `Emit` /
`EmitBatch` are *logged* error returns that the caller can ignore.
`Check` returns a real error because the caller needs it to decide
whether to invoke the tool.

### Strict envelope (W1 conformance)

`AgentTraceEvent` is unmarshalled via a custom `UnmarshalJSON` that
uses `json.Decoder.DisallowUnknownFields()`. This matches Pydantic
`extra="forbid"`, Zod `.strict()`, and serde `deny_unknown_fields`.

Enum strictness (W4): every enum is a typed `string` with explicit
constants and an `UnmarshalJSON` that rejects unknown values. The same
shape that the Python and TypeScript SDKs use.

### Bearer-token resolution (ADR-007 parity)

`resolveAPIToken(opts.APIKey)` in `auth.go` follows the same order as
the other SDKs:

1. Explicit `APIKey` on `ClientOptions` / `GuardianOptions`.
2. `TRUSTLAYER_API_TOKEN` environment variable.
3. None — no `Authorization` header sent.

### Dependencies

The Go SDK depends on:

- **stdlib only** for HTTP, JSON, time, and context.
- **`github.com/google/uuid`** for UUID v4 generation.

That's it. No HTTP framework, no logging dep, no test framework beyond
`testing` (with `httptest` from stdlib). The agent process pulls in
nothing it didn't already have.

### Go version support

- **Minimum supported version:** Go 1.22.
- **CI matrix:** Go 1.22 and 1.23.

Pre-1.22 isn't worth supporting — the standard library's HTTP routing
got cleaner in 1.22 and 1.21 is approaching EOL.

### Conformance claim

The Go SDK claims **wire-format conformance** (spec/v0.1/06-
conformance.md §6.2) — W1 through W7. It does not implement the policy
engine (P1–P6) or HTTP API (H1–H6) surfaces; those remain the Rust
sidecar's job. A Go agent uses the Go SDK to emit and check, and talks
HTTP to the sidecar for guardian + trace-store calls.

A cross-language test in `core-rs/tests/cross_language.rs` parses a
Go-emitted fixture so wire-format parity is enforced in CI.

### What we are *not* doing

- **No Go-side trace store.** The sidecar is the trace store; the Go
  SDK only emits.
- **No Go-side policy evaluator.** Same reason. A future ADR could
  embed the Rust policy engine via `cgo`, but that's a separate
  conversation from "ship a Go SDK".
- **No code generation from the spec.** The handwritten schema is the
  reference; if drift becomes a real problem we'll add the
  conformance fixture (ADR-010 follow-up) before any code-gen.
- **No retry / exponential backoff on `Emit`.** Instrumentation
  swallows failures; if a network blip drops an event, that's
  acceptable for v0.1 — agents that need at-least-once should write
  to a local JSONL and have a separate shipper tail it.

## Consequences

- **+** TrustLayer becomes reachable from the Go agent ecosystem with
  zero ceremony.
- **+** The spec gets its first proof-by-third-language: writing the
  Go SDK against `spec/v0.1/` (rather than against the Python SDK's
  internals) sharpens any ambiguity in §1–§6.
- **+** Conformance becomes a checkable claim on the v0.1 page.
- **−** Another language in the CI matrix → slightly longer CI runs.
  Negligible: the Go suite is small and parallel.
- **−** Schema drift now has four implementations to keep in sync. We
  mitigate by the cross-language test fixture and by the
  `CONTRIBUTING.md` rule that schema changes touch every mirror in
  one PR.

## Follow-ups
- Language-agnostic conformance fixture set under
  `spec/v0.1/fixtures/`, exercised by every SDK's test suite (ADR-010
  follow-up).
- A Go integration with OpenTelemetry export (Slice 4 item, separate
  ADR).
- `Tracer.ToolCall` could grow a streaming-result helper for tools
  that return multiple chunks. Defer until a real consumer asks.
