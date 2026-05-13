from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from trustlayer.schema import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
    Metrics,
    PolicyCheckPayload,
    PolicyCheckResult,
    ToolCallPayload,
    ToolResultPayload,
)


@pytest.fixture
def make_event():
    """Factory producing AgentTraceEvent records with explicit timestamps.

    Each call advances a monotonically increasing trace_id for stable
    ordering in tests.
    """
    base = datetime(2026, 5, 7, 9, 0, 0, tzinfo=timezone.utc)
    counter = {"i": 0}

    def _build(
        *,
        agent_id: str = "researcher",
        session_id: str = "session-1",
        event_type: EventType = EventType.AGENT_START,
        payload: dict[str, Any] | None = None,
        latency_ms: float | None = None,
        offset_seconds: float | None = None,
        cynefin_domain: CynefinDomain = CynefinDomain.DISORDER,
        trace_id: UUID | None = None,
    ) -> AgentTraceEvent:
        counter["i"] += 1
        return AgentTraceEvent(
            trace_id=trace_id or uuid4(),
            agent_id=agent_id,
            session_id=session_id,
            timestamp=base + timedelta(seconds=offset_seconds or counter["i"]),
            event_type=event_type,
            cynefin_domain=cynefin_domain,
            payload=payload or {},
            metrics=Metrics(latency_ms=latency_ms),
        )

    return _build


@pytest.fixture
def sample_session(make_event) -> list[AgentTraceEvent]:
    """A typical agent session: start -> tool_call/result x2 -> policy_fail -> end."""
    return [
        make_event(event_type=EventType.AGENT_START, payload={"goal": "answer math"}),
        make_event(
            event_type=EventType.TOOL_CALL,
            payload=ToolCallPayload(
                tool_name="calculator", tool_args={"expr": "2+2"}
            ).model_dump(),
        ),
        make_event(
            event_type=EventType.TOOL_RESULT,
            payload=ToolResultPayload(tool_name="calculator", result=4).model_dump(),
            latency_ms=12.0,
        ),
        make_event(
            event_type=EventType.TOOL_CALL,
            payload=ToolCallPayload(
                tool_name="calculator", tool_args={"expr": "1/0"}
            ).model_dump(),
        ),
        make_event(
            event_type=EventType.TOOL_RESULT,
            payload=ToolResultPayload(
                tool_name="calculator", error="ZeroDivisionError()"
            ).model_dump(),
            latency_ms=4.0,
        ),
        make_event(
            event_type=EventType.POLICY_CHECK,
            payload=PolicyCheckPayload(
                policy_name="pii_redaction",
                action="send_to_llm",
                result=PolicyCheckResult.FAIL,
                reason="Contains SSN",
            ).model_dump(),
        ),
        make_event(event_type=EventType.AGENT_END, payload={"status": "ok"}),
    ]
