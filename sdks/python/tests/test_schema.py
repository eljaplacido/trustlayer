from datetime import datetime
from uuid import UUID

import pytest

from trustlayer import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
    Metrics,
    PolicyCheckPayload,
    PolicyCheckResult,
    ToolCallPayload,
)


def test_agent_trace_event_defaults() -> None:
    event = AgentTraceEvent(
        agent_id="researcher-1",
        session_id="s1",
        event_type=EventType.AGENT_START,
    )
    assert isinstance(event.trace_id, UUID)
    assert isinstance(event.timestamp, datetime)
    assert event.cynefin_domain is CynefinDomain.DISORDER
    assert event.metrics.cost_usd is None
    assert event.payload == {}


def test_event_round_trip() -> None:
    original = AgentTraceEvent(
        agent_id="a",
        session_id="s",
        event_type=EventType.TOOL_CALL,
        payload=ToolCallPayload(tool_name="search", tool_args={"q": "x"}).model_dump(),
        metrics=Metrics(latency_ms=12.5, cost_usd=0.0001),
    )
    raw = original.model_dump_json()
    parsed = AgentTraceEvent.model_validate_json(raw)
    assert parsed.trace_id == original.trace_id
    assert parsed.payload["tool_name"] == "search"
    assert parsed.metrics.latency_ms == 12.5


def test_policy_check_payload_enum_round_trip() -> None:
    payload = PolicyCheckPayload(
        policy_name="pii_redaction",
        action="send_to_llm",
        result=PolicyCheckResult.FAIL,
        reason="Contains SSN",
    )
    raw = payload.model_dump_json()
    parsed = PolicyCheckPayload.model_validate_json(raw)
    assert parsed.result is PolicyCheckResult.FAIL


def test_unknown_top_level_field_rejected() -> None:
    with pytest.raises(Exception):
        AgentTraceEvent.model_validate(
            {
                "agent_id": "a",
                "session_id": "s",
                "event_type": EventType.AGENT_START.value,
                "unexpected": "nope",
            }
        )


def test_metrics_allows_extra_keys() -> None:
    metrics = Metrics.model_validate({"latency_ms": 1.0, "custom_metric": 99})
    assert metrics.model_dump()["custom_metric"] == 99
