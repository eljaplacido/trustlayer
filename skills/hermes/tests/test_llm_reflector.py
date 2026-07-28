"""Tests for the LLM-backed reflection engine (ADR-013)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from hermes.llm_reflector import (
    LLMReflector,
    _build_prompt,
    _extract_ollama_content,
    _fallback_narrative,
)
from hermes.reflector import DeterministicReflector, Reflection, SessionSummary
from trustlayer.schema import (
    AgentTraceEvent,
    EventType,
    Metrics,
    ToolCallPayload,
    ToolResultPayload,
)


def _session(agent: str, session: str, tool_names: list[str]) -> list[AgentTraceEvent]:
    """Build a minimal session with tool calls and results."""
    events: list[AgentTraceEvent] = []
    start = AgentTraceEvent(
        trace_id=uuid4(),
        agent_id=agent,
        session_id=session,
        timestamp=datetime.now(UTC),
        event_type=EventType.AGENT_START,
        payload={"goal": "test"},
    )
    events.append(start)
    for i, name in enumerate(tool_names):
        tc = AgentTraceEvent(
            trace_id=uuid4(),
            agent_id=agent,
            session_id=session,
            timestamp=datetime.now(UTC),
            event_type=EventType.TOOL_CALL,
            payload=ToolCallPayload(tool_name=name, tool_args={"n": i}).model_dump(),
            metrics=Metrics(latency_ms=10.0),
        )
        events.append(tc)
        tr = AgentTraceEvent(
            trace_id=uuid4(),
            agent_id=agent,
            session_id=session,
            timestamp=datetime.now(UTC),
            event_type=EventType.TOOL_RESULT,
            payload=ToolResultPayload(tool_name=name, result={"ok": True}).model_dump(),
            metrics=Metrics(latency_ms=5.0),
        )
        events.append(tr)
    end = AgentTraceEvent(
        trace_id=uuid4(),
        agent_id=agent,
        session_id=session,
        timestamp=datetime.now(UTC),
        event_type=EventType.AGENT_END,
        payload={"status": "ok"},
    )
    events.append(end)
    return events


def _mock_ollama_transport(content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"content": content}, "model": "test-model"},
        )

    return httpx.MockTransport(handler)


def _error_transport(status: int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    return httpx.MockTransport(handler)


class TestLLMReflector:
    def test_falls_back_when_llm_unreachable(self):
        transport = _error_transport(503)
        reflector = LLMReflector(
            endpoint="http://localhost:11434/api/chat",
            model="test",
            transport=transport,
        )
        events = _session("a", "s1", ["calc", "search"])
        det = DeterministicReflector()
        summary = det.summarise_session(events)
        result = reflector.synthesise([summary])
        assert "No LLM narrative available" in result.headline_metrics["narrative"]
        assert reflector.last_error is not None

    def test_uses_llm_when_reachable(self):
        expected = "All clear. No anomalies in this period."
        transport = _mock_ollama_transport(expected)
        reflector = LLMReflector(
            endpoint="http://localhost:11434/api/chat",
            model="test",
            transport=transport,
        )
        events = _session("a", "s1", ["calc"])
        det = DeterministicReflector()
        summary = det.summarise_session(events)
        result = reflector.synthesise([summary])
        assert result.headline_metrics["narrative"] == expected
        assert reflector.last_error is None

    def test_falls_back_on_empty_llm_response(self):
        transport = _mock_ollama_transport("   ")
        reflector = LLMReflector(
            endpoint="http://localhost:11434/api/chat",
            model="test",
            transport=transport,
        )
        events = _session("a", "s1", ["calc"])
        det = DeterministicReflector()
        summary = det.summarise_session(events)
        result = reflector.synthesise([summary])
        assert "No LLM narrative available" in result.headline_metrics["narrative"]

    def test_falls_back_on_http_error(self):
        transport = _error_transport(500)
        reflector = LLMReflector(transport=transport)
        events = _session("a", "s1", ["calc"])
        det = DeterministicReflector()
        summary = det.summarise_session(events)
        result = reflector.synthesise([summary])
        assert "No LLM narrative available" in result.headline_metrics["narrative"]

    def test_reflect_narrative_returns_structured_plus_text(self):
        expected = "Session had 2 tool calls. No policy violations."
        transport = _mock_ollama_transport(expected)
        reflector = LLMReflector(model="test-model", transport=transport)
        events = _session("a", "s1", ["calc", "search"])
        det = DeterministicReflector()
        summary = det.summarise_session(events)
        result = reflector.reflect_narrative([summary])
        assert result.text == expected
        assert result.model == "test-model"
        assert result.structured.headline_metrics["sessions"] == 1
        assert len(result.structured.top_tools) == 2

    def test_llm_reflector_provides_both_methods(self):
        reflector = LLMReflector(transport=_error_transport(503))
        assert callable(reflector.summarise_session)
        assert callable(reflector.synthesise)


class TestBuildPrompt:
    def test_includes_headline_metrics(self):
        summary = SessionSummary(
            agent_id="a",
            session_id="s",
            event_count=5,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
        )
        reflection = Reflection(
            date=datetime.now(UTC).date(),
            headline_metrics={
                "sessions": 1,
                "events": 5,
                "tool_invocations": 3,
                "tool_errors": 0,
                "total_latency_ms": 45.0,
            },
            top_tools=[("calc", 3)],
            policy_failures=[],
        )
        prompt = _build_prompt([summary], reflection)
        assert "**sessions:** 1" in prompt
        assert "**events:** 5" in prompt
        assert "calc" in prompt
        assert "Per-session summaries" in prompt

    def test_includes_policy_failures(self):
        summary = SessionSummary(
            agent_id="a",
            session_id="s",
            event_count=3,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            policy_failures=[{"policy": "default", "action": "invoke shell", "reason": "blocked"}],
        )
        reflection = Reflection(
            date=datetime.now(UTC).date(),
            headline_metrics={
                "sessions": 1,
                "events": 3,
                "tool_invocations": 0,
                "tool_errors": 0,
                "total_latency_ms": 0.0,
            },
            top_tools=[],
            policy_failures=[{"policy": "default", "action": "invoke shell", "count": 1}],
        )
        prompt = _build_prompt([summary], reflection)
        assert "Policy failures" in prompt
        assert "invoke shell" in prompt
        assert "1x" in prompt


class TestExtractContent:
    def test_extracts_ollama_chat_format(self):
        data = {"message": {"content": "hello"}}
        assert _extract_ollama_content(data) == "hello"

    def test_returns_empty_string_on_missing_key(self):
        assert _extract_ollama_content({}) == ""


class TestFallbackNarrative:
    def test_produces_readable_summary(self):
        reflection = Reflection(
            date=datetime.now(UTC).date(),
            headline_metrics={
                "sessions": 3,
                "events": 42,
                "tool_invocations": 30,
                "tool_errors": 2,
                "total_latency_ms": 500.0,
            },
            top_tools=[],
            policy_failures=[{"policy": "default", "action": "invoke shell", "count": 1}],
        )
        text = _fallback_narrative(reflection)
        assert "3 session" in text
        assert "42 events" in text
        assert "30 tool invocation" in text
        assert "2 tool error" in text
        assert "policy failure" in text
        assert "LLM endpoint was unreachable" in text

    def test_no_errors_when_clean(self):
        reflection = Reflection(
            date=datetime.now(UTC).date(),
            headline_metrics={
                "sessions": 1,
                "events": 4,
                "tool_invocations": 2,
                "tool_errors": 0,
                "total_latency_ms": 20.0,
            },
            top_tools=[],
            policy_failures=[],
        )
        text = _fallback_narrative(reflection)
        assert "policy failure" not in text
        assert "tool error" not in text
