"""OpenTelemetry bridge for TrustLayer events (ADR-012).

Turn each :class:`AgentTraceEvent` into one OTel span using the caller's
already-configured ``TracerProvider``. The OTel SDK itself is an
optional dependency: install with ``pip install trustlayer-sdk[otel]``
to pull it in. Code that doesn't import this module never sees OTel in
its dependency tree.

Typical wiring:

    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )

    otel_trace.set_tracer_provider(TracerProvider())
    otel_trace.get_tracer_provider().add_span_processor(
        BatchSpanProcessor(ConsoleSpanExporter()),
    )

    from trustlayer.otel import OTelExporter

    exporter = OTelExporter(tracer=otel_trace.get_tracer("my-agent"))
    exporter.emit(event)            # one span
    exporter.emit_batch([e1, e2])   # one span per event

The exporter mirrors :class:`trustlayer.TrustLayerClient` method-for-
method (``emit`` / ``emit_batch``) so callers can swap transports by
changing one import line.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from .schema import AgentTraceEvent, EventType


class _OTelTracer(Protocol):
    """Structural type for the bits of ``opentelemetry.trace.Tracer`` we use."""

    def start_span(
        self, name: str, start_time: int | None = ..., attributes: Mapping[str, Any] | None = ...
    ) -> Any: ...


class OTelExporter:
    """Maps ``AgentTraceEvent`` to OTel spans using a caller-supplied tracer.

    The exporter owns no transport: shipping happens through whatever
    ``SpanProcessor`` / ``SpanExporter`` the caller has registered on
    their ``TracerProvider`` (OTLP, Jaeger, console, in-memory, …).
    """

    def __init__(self, tracer: _OTelTracer) -> None:
        self._tracer = tracer

    # ----------------------------------------------------------------- emit
    def emit(self, event: AgentTraceEvent) -> None:
        """Emit one OTel span for ``event``."""
        name = _span_name(event)
        start_ns = _to_ns(event.timestamp.timestamp())
        end_ns = _end_time_ns(event, start_ns)
        attrs = _flatten_attributes(event)
        span = self._tracer.start_span(name, start_time=start_ns, attributes=attrs)
        span.end(end_time=end_ns)

    def emit_batch(self, events: Iterable[AgentTraceEvent]) -> None:
        """Emit one OTel span per event, in iteration order."""
        for event in events:
            self.emit(event)


# ─── span name ────────────────────────────────────────────────────────────


def _span_name(event: AgentTraceEvent) -> str:
    """Pick a human-readable span name. See ADR-012 §"Mapping"."""
    payload = event.payload or {}
    et = event.event_type
    if et in {EventType.TOOL_CALL, EventType.TOOL_RESULT}:
        tool = payload.get("tool_name")
        if isinstance(tool, str) and tool:
            return tool
    if et == EventType.LLM_CALL:
        model = payload.get("model")
        if isinstance(model, str) and model:
            return f"llm:{model}"
    if et == EventType.POLICY_CHECK:
        policy = payload.get("policy_name")
        if isinstance(policy, str) and policy:
            return f"policy:{policy}"
    return et.value


# ─── timing ───────────────────────────────────────────────────────────────


def _to_ns(seconds: float) -> int:
    """Convert epoch seconds (float) to nanoseconds (int) for OTel."""
    return int(seconds * 1_000_000_000)


def _end_time_ns(event: AgentTraceEvent, start_ns: int) -> int:
    """Compute span end time. Uses metrics.latency_ms when present."""
    latency_ms = getattr(event.metrics, "latency_ms", None)
    if latency_ms is None:
        return start_ns
    return start_ns + int(float(latency_ms) * 1_000_000)


# ─── attribute flattening ────────────────────────────────────────────────


def _flatten_attributes(event: AgentTraceEvent) -> dict[str, Any]:
    """Build the span attributes dict from the envelope, payload, and metrics.

    OTel attribute values can be: bool, str, int, float, or homogeneous
    sequences of those. We coerce anything more complex into a JSON
    string so the export pipeline never has to throw — losing structure
    in dashboards is preferable to dropping the event.
    """
    attrs: dict[str, Any] = {
        "trustlayer.trace_id": str(event.trace_id),
        "trustlayer.agent_id": event.agent_id,
        "trustlayer.session_id": event.session_id,
        "trustlayer.event_type": event.event_type.value,
        "trustlayer.cynefin_domain": event.cynefin_domain.value,
    }
    _flatten_into(attrs, "trustlayer.payload", event.payload or {})
    _flatten_into(attrs, "trustlayer.metrics", _metrics_to_dict(event))
    return attrs


def _metrics_to_dict(event: AgentTraceEvent) -> dict[str, Any]:
    """Render the Metrics model as a dict suitable for flattening.

    Uses Pydantic's ``model_dump`` so well-known fields appear with their
    declared keys and the ``extra`` passthrough (Metrics carries
    ``model_config = ConfigDict(extra="allow")``) survives.
    """
    if event.metrics is None:
        return {}
    dump = event.metrics.model_dump(exclude_none=True, by_alias=True, mode="json")
    if not isinstance(dump, dict):
        return {}
    return dump


def _flatten_into(out: dict[str, Any], prefix: str, value: Any) -> None:
    """Walk ``value`` and write OTel-compatible attribute entries to ``out``.

    Nested dicts are joined with ``.``; lists/tuples become indexed
    keys (``.0``, ``.1``, …). Anything that can't be expressed cleanly
    in OTel's attribute type system is stringified.
    """
    if isinstance(value, Mapping):
        for k, v in value.items():
            _flatten_into(out, f"{prefix}.{k}", v)
        return
    if isinstance(value, (list, tuple)):
        # Homogeneous primitive sequences stay as sequences (OTel-native).
        if value and all(isinstance(item, (bool, int, float, str)) for item in value):
            # Avoid mixing bool with int in OTel attribute lists: coerce to a
            # uniform stringified form when mixed types appear.
            types = {type(item) for item in value}
            if len(types) == 1:
                out[prefix] = list(value)
                return
            out[prefix] = [str(item) for item in value]
            return
        for i, item in enumerate(value):
            _flatten_into(out, f"{prefix}.{i}", item)
        return
    if value is None:
        # OTel rejects None — drop the key rather than emit a null.
        return
    if isinstance(value, (bool, int, float, str)):
        out[prefix] = value
        return
    # Fallback: stringify so dashboards still see something.
    out[prefix] = str(value)
