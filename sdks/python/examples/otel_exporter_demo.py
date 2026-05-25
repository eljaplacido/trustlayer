"""End-to-end demo for the OTel exporter (ADR-012).

Wires up the OpenTelemetry SDK with a ``ConsoleSpanExporter`` so each
emitted ``AgentTraceEvent`` prints as a span on stdout. Real
deployments swap ``ConsoleSpanExporter`` for ``OTLPSpanExporter`` (or
Jaeger, Zipkin, …) — the ``OTelExporter`` line below does not change.

Run::

    pip install -e sdks/python[otel]
    python sdks/python/examples/otel_exporter_demo.py
"""

from __future__ import annotations

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from trustlayer import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
    Metrics,
)
from trustlayer.otel import OTelExporter


def main() -> None:
    # 1. Stand up a TracerProvider with whatever exporter we want.
    #    ConsoleSpanExporter is the demo's choice; production uses OTLP.
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    otel_trace.set_tracer_provider(provider)
    otel_tracer = otel_trace.get_tracer("trustlayer.demo")

    # 2. Wrap the OTel tracer in the TrustLayer bridge.
    exporter = OTelExporter(tracer=otel_tracer)

    # 3. Emit a small mixed stream so the console shows all the span
    #    names + attribute shapes the bridge produces.
    exporter.emit(
        AgentTraceEvent(
            agent_id="researcher-1",
            session_id="S1",
            event_type=EventType.AGENT_START,
        ),
    )
    exporter.emit(
        AgentTraceEvent(
            agent_id="researcher-1",
            session_id="S1",
            event_type=EventType.TOOL_CALL,
            cynefin_domain=CynefinDomain.COMPLEX,
            payload={"tool_name": "external_llm", "tool_args": {"prompt": "hi"}},
            metrics=Metrics(latency_ms=12.5, cost_usd=0.0015),
        ),
    )
    exporter.emit(
        AgentTraceEvent(
            agent_id="researcher-1",
            session_id="S1",
            event_type=EventType.POLICY_CHECK,
            payload={
                "policy_name": "default",
                "action": "external_llm",
                "result": "FAIL",
                "reason": "PII",
            },
        ),
    )
    exporter.emit(
        AgentTraceEvent(
            agent_id="researcher-1",
            session_id="S1",
            event_type=EventType.AGENT_END,
            payload={"status": "completed"},
        ),
    )

    # Flush any buffered spans so the demo output is complete.
    provider.shutdown()


if __name__ == "__main__":
    main()
