---
adr: 012
status: accepted
date: 2026-05-25
tags: [architecture, phase-6, otel, observability, interop]
supersedes: []
extends: ["[[ADR-001-SDK-Wedge]]", "[[ADR-010-Formal-Spec-Layout]]"]
---

# ADR-012 — OpenTelemetry exporter for TrustLayer events

## Context

The audit's "Nice-to-have #14" called this out directly:

> No OpenTelemetry integration — The schema is OTel-inspired but
> there's no OTel exporter. This limits adoption in existing
> observability stacks.

That's the rub. Most production environments already run an OTel
pipeline pointing at Jaeger / Tempo / Honeycomb / Grafana / Datadog /
whatever. An adopter who runs TrustLayer alongside that pipeline today
has to choose: stand up a second pipeline for `AgentTraceEvent`s, or
write a one-off bridge.

The right answer is a first-party bridge: a small adapter that lets
the host's existing OTel `TracerProvider` consume TrustLayer events
without TrustLayer caring which downstream exporter ends up shipping
the data.

## Decision

Ship a Python module `trustlayer.otel` whose `OTelExporter` turns
each `AgentTraceEvent` into one OTel span using the caller's already-
configured `TracerProvider`. The OTel SDKs themselves are a Python
**extra** of `trustlayer-sdk`:

```bash
pip install trustlayer-sdk[otel]
```

so the base SDK keeps a stdlib-only dependency posture for users who
do not want OTel.

### Mapping

One `AgentTraceEvent` → one OTel span. The mapping is lossless: every
envelope, payload, and metrics field is reachable from the span.

| TrustLayer | OTel span field |
|---|---|
| `event_type`, `payload.tool_name` or `payload.model` (when relevant) | `span.name` |
| `timestamp` | `span.start_time` |
| `timestamp` + `metrics.latency_ms` (or zero) | `span.end_time` |
| `trace_id` | `span.attributes["trustlayer.trace_id"]` |
| `agent_id`, `session_id`, `event_type`, `cynefin_domain` | `span.attributes["trustlayer.*"]` |
| `payload.*` (depth-flattened JSON path) | `span.attributes["trustlayer.payload.*"]` |
| `metrics.*` (flattened) | `span.attributes["trustlayer.metrics.*"]` |

Span name rules:

- `TOOL_CALL` / `TOOL_RESULT` with `payload.tool_name` → that name.
- `LLM_CALL` with `payload.model` → `"llm:<model>"`.
- `POLICY_CHECK` → `"policy:<policy_name>"` if present, else
  `"POLICY_CHECK"`.
- Anything else → the `event_type` value verbatim.

The name is a quality-of-life concern for dashboards; conformance and
correctness come from the attributes.

### Duration

A single `AgentTraceEvent` represents a point in time, but OTel spans
have a duration. We use:

- `start_time = event.timestamp`.
- `end_time = event.timestamp + event.metrics.latency_ms` when
  `latency_ms` is present.
- `end_time = event.timestamp` (zero-duration span) otherwise.

OTel allows zero-duration spans; backends render them as instantaneous
events. We deliberately do not try to pair TOOL_CALL with TOOL_RESULT
into a single multi-second span — that's a lossy join the exporter
cannot do correctly when events arrive out of order, and it would
hide the policy-check that often sits between them.

### Trace / span ID handling

OTel's own `trace_id` is 128 bits; TrustLayer's is a UUID v4 (128
bits). We deliberately **do not** reuse TrustLayer's `trace_id` as
the OTel `trace_id`. The two IDs serve different purposes:

- OTel `trace_id`: groups spans that belong to one *distributed
  trace*. The OTel SDK manages it via context propagation.
- TrustLayer `trace_id`: identifies one *agent event*. Each event has
  its own.

Reusing the TrustLayer ID would force every event into its own OTel
trace, which defeats correlation in OTel dashboards. Instead we let
the caller's OTel context dictate trace grouping (e.g. one
`session_id` ↔ one OTel trace, owned by the caller via
`tracer.start_as_current_span` around the agent's session loop), and
we expose the TrustLayer `trace_id` as a *span attribute* so it
remains queryable.

### Public surface

```python
from opentelemetry import trace as otel_trace
from trustlayer import AgentTraceEvent, EventType
from trustlayer.otel import OTelExporter

# Caller wires up their TracerProvider + exporter (OTLP, Jaeger, etc.)
otel_tracer = otel_trace.get_tracer("my-agent")

exporter = OTelExporter(tracer=otel_tracer)
exporter.emit(event)            # one span
exporter.emit_batch([e1, e2])   # one span per event
```

`OTelExporter` deliberately mirrors `TrustLayerClient.emit` /
`emit_batch` so callers can swap between transports by changing one
import line.

### Not part of this ADR

- **Sidecar-side OTLP receiver.** Letting the Rust sidecar *accept*
  OTLP-shaped events and translate them to `AgentTraceEvent` is a
  separate ADR. The current direction (TrustLayer → OTel) is the
  audit ask.
- **gRPC OTLP client.** We don't ship one; users plug their own
  exporter into the `TracerProvider`. That keeps the dependency
  footprint of the `otel` extra small (`opentelemetry-api` +
  `opentelemetry-sdk`, no transport-specific deps).
- **TypeScript / Go OTel exporter.** Same conceptual mapping, but
  one language at a time. The Python module is the reference and
  fixes the attribute naming convention; the others follow in later
  slices if needed.
- **OTel logs / metrics signals.** We map only to *traces* in v1.
  Logs / metrics signals can be added later by attribute or by a
  second exporter class.

## Tests

- Use OTel SDK's `InMemorySpanExporter` to capture spans emitted by
  `OTelExporter.emit(...)` and assert the mapping above:
    - span name for each event_type
    - all envelope fields surfaced as attributes
    - payload + metrics depth-flattening
    - duration math with and without `latency_ms`
    - emit_batch produces one span per event in order

## Consequences

- **+** Any OTel pipeline can consume TrustLayer events with one
  import-line change and a `pip install …[otel]`.
- **+** The Python SDK still has zero hard OTel dependency; the
  extra is opt-in.
- **+** The exporter is testable end-to-end without a network
  pipeline thanks to `InMemorySpanExporter`.
- **+** Reusing the caller's `TracerProvider` lets context
  propagation, sampling, and resource detection all stay in the
  OTel world. We don't reinvent any of it.
- **−** Span names are heuristic. Dashboard authors may want richer
  conventions per event type; we accept that until a real consumer
  asks for it.
- **−** Two TrustLayer events that *should* be a single span (TOOL_
  CALL + TOOL_RESULT) appear as two zero-duration siblings. This is
  the right tradeoff for v1 — we never lose the second event when
  out-of-order delivery happens — but a future "pairing" mode could
  add the join.

## Follow-ups
- TypeScript exporter once a real consumer asks.
- Go exporter mirroring the same attribute names so dashboards stay
  cross-language portable.
- An optional `pair_tool_calls=True` mode that joins TOOL_CALL +
  TOOL_RESULT by `(session_id, payload.tool_name)` into a single
  span with duration = result_time − call_time.
- Map `cynefin_domain` to OTel semantic-convention attributes once
  the project picks names (probably under the `agent.*` prefix the
  GenAI working group is using).
