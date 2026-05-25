"""Tests for the OpenTelemetry exporter (ADR-012)."""

from __future__ import annotations

import pytest

# Skip the whole file when the OTel extra isn't installed. Pytest treats
# this as a collection-time skip with a clear reason.
otel_trace = pytest.importorskip("opentelemetry.trace")
otel_export = pytest.importorskip(
    "opentelemetry.sdk.trace.export.in_memory_span_exporter"
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from trustlayer import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
    Metrics,
)
from trustlayer.otel import OTelExporter


# A tracer wired up to an in-memory exporter for round-trip assertions.
@pytest.fixture
def captured_spans():
    provider = TracerProvider()
    exporter = otel_export.InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    return tracer, exporter


def _event(
    event_type: EventType = EventType.TOOL_CALL,
    payload: dict | None = None,
    metrics: Metrics | None = None,
    cynefin: CynefinDomain = CynefinDomain.COMPLEX,
) -> AgentTraceEvent:
    # Important: distinguish "no payload passed" (apply the default
    # tool_name) from "explicit empty dict" (caller wants no payload).
    return AgentTraceEvent(
        agent_id="researcher-1",
        session_id="S1",
        event_type=event_type,
        cynefin_domain=cynefin,
        payload=payload if payload is not None else {"tool_name": "external_llm"},
        metrics=metrics if metrics is not None else Metrics(),
    )


# ─── span name ───────────────────────────────────────────────────────────


def test_tool_call_span_uses_tool_name(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(_event(payload={"tool_name": "calc"}))
    spans = exp.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "calc"


def test_llm_call_span_uses_llm_model(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(
        _event(
            event_type=EventType.LLM_CALL,
            payload={"model": "gpt-4", "prompt": "hi"},
        )
    )
    spans = exp.get_finished_spans()
    assert spans[0].name == "llm:gpt-4"


def test_policy_check_span_uses_policy_name(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(
        _event(
            event_type=EventType.POLICY_CHECK,
            payload={"policy_name": "default", "action": "calc", "result": "PASS"},
        )
    )
    spans = exp.get_finished_spans()
    assert spans[0].name == "policy:default"


def test_other_event_types_fall_back_to_event_type(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(_event(event_type=EventType.AGENT_START, payload={}))
    spans = exp.get_finished_spans()
    assert spans[0].name == "AGENT_START"


def test_tool_call_without_tool_name_falls_back(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(_event(payload={}))
    spans = exp.get_finished_spans()
    assert spans[0].name == "TOOL_CALL"


# ─── attributes ──────────────────────────────────────────────────────────


def test_envelope_fields_become_attributes(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(_event())
    attrs = dict(exp.get_finished_spans()[0].attributes)
    assert attrs["trustlayer.agent_id"] == "researcher-1"
    assert attrs["trustlayer.session_id"] == "S1"
    assert attrs["trustlayer.event_type"] == "TOOL_CALL"
    assert attrs["trustlayer.cynefin_domain"] == "COMPLEX"
    # trace_id is a UUID string — present + non-empty.
    assert isinstance(attrs["trustlayer.trace_id"], str)
    assert len(attrs["trustlayer.trace_id"]) == 36


def test_payload_is_depth_flattened(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(
        _event(
            payload={
                "tool_name": "external_llm",
                "args": {"model": "gpt-4", "temperature": 1.0},
            }
        )
    )
    attrs = dict(exp.get_finished_spans()[0].attributes)
    assert attrs["trustlayer.payload.tool_name"] == "external_llm"
    assert attrs["trustlayer.payload.args.model"] == "gpt-4"
    assert attrs["trustlayer.payload.args.temperature"] == 1.0


def test_payload_list_of_primitives_stays_as_sequence(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(
        _event(payload={"args": {"tools": ["shell", "browser"]}})
    )
    attrs = dict(exp.get_finished_spans()[0].attributes)
    tools = attrs["trustlayer.payload.args.tools"]
    # OTel may normalise to a tuple — accept either ordered container.
    assert list(tools) == ["shell", "browser"]


def test_payload_mixed_list_is_indexed(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(
        _event(payload={"items": [{"name": "a"}, {"name": "b"}]})
    )
    attrs = dict(exp.get_finished_spans()[0].attributes)
    assert attrs["trustlayer.payload.items.0.name"] == "a"
    assert attrs["trustlayer.payload.items.1.name"] == "b"


def test_metrics_fields_become_attributes(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(
        _event(metrics=Metrics(latency_ms=12.5, cost_usd=0.0015, tokens_prompt=150))
    )
    attrs = dict(exp.get_finished_spans()[0].attributes)
    assert attrs["trustlayer.metrics.latency_ms"] == 12.5
    assert attrs["trustlayer.metrics.cost_usd"] == 0.0015
    assert attrs["trustlayer.metrics.tokens_prompt"] == 150


def test_metrics_extra_passthrough_becomes_attributes(captured_spans) -> None:
    tracer, exp = captured_spans
    m = Metrics(latency_ms=1.0)
    # Pydantic extra="allow" lets us stuff custom keys.
    m_dict = m.model_dump()
    m_dict["custom_score"] = 0.9
    event = _event(metrics=Metrics(**m_dict))
    OTelExporter(tracer).emit(event)
    attrs = dict(exp.get_finished_spans()[0].attributes)
    assert attrs["trustlayer.metrics.custom_score"] == 0.9


def test_none_values_are_dropped(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(_event(payload={"tool_name": "calc", "context": None}))
    attrs = dict(exp.get_finished_spans()[0].attributes)
    # `context: None` must not appear (OTel rejects None values).
    assert "trustlayer.payload.context" not in attrs


# ─── timing ──────────────────────────────────────────────────────────────


def test_zero_duration_span_when_no_latency(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(_event(metrics=Metrics()))
    span = exp.get_finished_spans()[0]
    assert span.end_time == span.start_time


def test_latency_drives_span_duration(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit(_event(metrics=Metrics(latency_ms=250.0)))
    span = exp.get_finished_spans()[0]
    delta_ns = span.end_time - span.start_time
    # 250 ms = 250 million ns. Allow a 1 ns rounding slack.
    assert abs(delta_ns - 250_000_000) <= 1


# ─── batch ───────────────────────────────────────────────────────────────


def test_emit_batch_produces_one_span_per_event_in_order(captured_spans) -> None:
    tracer, exp = captured_spans
    events = [
        _event(payload={"tool_name": "a"}),
        _event(payload={"tool_name": "b"}),
        _event(payload={"tool_name": "c"}),
    ]
    OTelExporter(tracer).emit_batch(events)
    names = [s.name for s in exp.get_finished_spans()]
    assert names == ["a", "b", "c"]


def test_emit_batch_empty_is_noop(captured_spans) -> None:
    tracer, exp = captured_spans
    OTelExporter(tracer).emit_batch([])
    assert exp.get_finished_spans() == ()
