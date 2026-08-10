# Conformance fixtures (v0.1)

This directory holds **deterministic JSON artifacts** that every
conforming implementation MUST be able to parse into an
`AgentTraceEvent` per [`spec/v0.1/01-wire-format.md`](../01-wire-format.md).

Fixtures are named `event-<subject>-<lang>.json`, where `<lang>` is the
SDK that produced them. They are byte-identical across runs because
their `trace_id` and `timestamp` are pinned to fixed values; that lets
us cite the same artifact across versions of the spec without
re-generating.

**Every implementation reads this directory.** The reference Rust core
(`core-rs/tests/cross_language.rs`) and all four SDKs glob it and assert
that each file parses under the strict envelope (W1), preserves every
envelope field, round-trips to a fixed point, and *rejects* an injected
unknown field:

| Implementation | Test |
|---|---|
| Rust core | `core-rs/tests/cross_language.rs` |
| Python SDK | `sdks/python/tests/test_conformance_fixtures.py` |
| TypeScript SDK | `sdks/typescript/tests/conformance.test.ts` |
| Go SDK | `sdks/go/trustlayer/conformance_test.go` |

Globbing rather than naming files means a fixture added here is covered
by all five the moment it is committed. A fixture read by only the
language that produced it proves nothing about interoperability — this
is the rule whose absence produced gap G0 (see `docs/PHASE-8-DESIGN.md`
§5.3).

The glob is scoped to the `event-` prefix, because this directory also
holds **conformance tables** that are deliberately not events:

| File | What it is | Read by |
|---|---|---|
| `predicate-cases.json` | Shared table of payload-predicate cases (spec §4.3, ADR-018) | `core-rs/tests/predicate_conformance.rs`, `compliance/tests/test_predicates.py` |

A table like this exists for the same reason the event fixtures do. The
predicate language is implemented twice — once in the Rust policy engine,
once in the Python evidence engine — and a language implemented twice and
tested twice will diverge. Divergence there means a control can claim to
be enforced by a rule that does not match the same events.

## Current fixtures

| File | Subject | Producer | Reproduce (from `sdks/go/`) |
|---|---|---|---|
| `event-canonical-go.json` | `TOOL_CALL` with full metrics | Go SDK | `go run ./examples/conformance canonical > ../../spec/v0.1/fixtures/event-canonical-go.json` |
| `event-tool-result-go.json` | `TOOL_RESULT` closing the canonical call, `error` an explicit null (§2.3) | Go SDK | `go run ./examples/conformance tool-result > ../../spec/v0.1/fixtures/event-tool-result-go.json` |
| `event-llm-call-go.json` | `LLM_CALL` with token and cost accounting (§2.4) | Go SDK | `go run ./examples/conformance llm-call > ../../spec/v0.1/fixtures/event-llm-call-go.json` |
| `event-policy-check-go.json` | `POLICY_CHECK`, the `FAIL` branch so `reason` is non-null (§2.5) | Go SDK | `go run ./examples/conformance policy-check > ../../spec/v0.1/fixtures/event-policy-check-go.json` |
| `event-human-escalation-go.json` | `HUMAN_ESCALATION`, the event `event-human-decision-go.json` resolves (§2.6) | Go SDK | `go run ./examples/conformance human-escalation > ../../spec/v0.1/fixtures/event-human-escalation-go.json` |
| `event-agent-end-go.json` | `AGENT_END` closing the `researcher-1` session (§2.7) | Go SDK | `go run ./examples/conformance agent-end > ../../spec/v0.1/fixtures/event-agent-end-go.json` |
| `event-disclosure-shown-go.json` | `DISCLOSURE_SHOWN`, Art. 50(1) (§2.8) | Go SDK | `go run ./examples/conformance disclosure-shown > ../../spec/v0.1/fixtures/event-disclosure-shown-go.json` |
| `event-content-marked-go.json` | `CONTENT_MARKED` with a `verification` block, Art. 50(2) (§2.9) | Go SDK | `go run ./examples/conformance content-marked > ../../spec/v0.1/fixtures/event-content-marked-go.json` |
| `event-human-decision-go.json` | `HUMAN_DECISION`, the outcome of an escalation, Art. 14 (§2.10) | Go SDK | `go run ./examples/conformance human-decision > ../../spec/v0.1/fixtures/event-human-decision-go.json` |
| `event-harness-snapshot-go.json` | `HARNESS_SNAPSHOT`, the configuration a session ran under, Art. 43 (§2.11) | Go SDK | `go run ./examples/conformance harness-snapshot > ../../spec/v0.1/fixtures/event-harness-snapshot-go.json` |
| `event-delegated-go.json` | `AGENT_START` carrying `parent_trace_id` — sub-agent delegation (§1.3) | Go SDK | `go run ./examples/conformance delegated > ../../spec/v0.1/fixtures/event-delegated-go.json` |

## Adding a new fixture

1. Add a builder to your SDK's `examples/conformance/` generator, keyed
   by a CLI name.
2. Pin the `trace_id`, `timestamp`, payload, and metrics so successive
   runs are byte-identical. Regenerating an unchanged fixture must
   produce no diff.
3. Commit the generator's output as `event-<subject>-<lang>.json` here
   and add a row to the table above.
4. Add a field-level assertion in `core-rs/tests/cross_language.rs`.
   The generic checks (strict envelope, field preservation, round-trip,
   unknown-field rejection) apply automatically via the glob in all five
   implementations, but a fixture with no *subject-specific* assertion
   only proves it parses — not that it carries the payload the spec
   section describes.

## Every event type must appear here

`compliance/tests/test_event_type_lockstep.py` asserts that each of the
event types declared in `core-rs` `EventType` is carried by at least one
committed fixture, and separately that the Python, TypeScript and Go SDK
enums match that same reference set.

Both checks exist because the original G0 fix left a hole. It pinned the
Rust enum to the spec prose and to `compliance/schemas/control.schema.json`
— so a new event type added to those three places passed, while the four
SDKs stayed behind and nothing failed. The SDKs were covered only
indirectly, by round-tripping the files in this directory, which catches a
missing type *only if someone also remembered to add a fixture for it*.
Five of the eleven types had none.
