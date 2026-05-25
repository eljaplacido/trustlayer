# Conformance fixtures (v0.1)

This directory holds **deterministic JSON artifacts** that every
conforming implementation MUST be able to parse into an
`AgentTraceEvent` per [`spec/v0.1/01-wire-format.md`](../01-wire-format.md).

Each fixture is named for the SDK that produced it. They are
byte-identical across runs because their `trace_id` and `timestamp`
are pinned to fixed values; that lets us cite the same artifact
across versions of the spec without re-generating.

The reference Rust core's cross-language test
(`core-rs/tests/cross_language.rs`) loads every file here and asserts
it parses with the strict envelope (W1) plus expected field values.

## Current fixtures

| File | Producer | Reproduce |
|---|---|---|
| `event-canonical-go.json` | Go SDK (`sdks/go/`) | `cd sdks/go && go run ./examples/conformance > ../../spec/v0.1/fixtures/event-canonical-go.json` |

## Adding a new fixture

1. Add a deterministic generator to your SDK's `examples/conformance/`
   directory.
2. Pin the `trace_id`, `timestamp`, payload, and metrics so successive
   runs are byte-identical.
3. Commit the generator's output as
   `event-canonical-<lang>.json` in this directory.
4. Reference the file from
   `core-rs/tests/cross_language.rs` so the test runs against the new
   SDK's emitted bytes.
