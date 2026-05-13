from __future__ import annotations

import pytest

from hermes.reflector import DeterministicReflector, Reflection, SessionSummary


def test_summarise_session_counts_tools_and_errors(sample_session):
    summary = DeterministicReflector().summarise_session(sample_session)
    assert isinstance(summary, SessionSummary)
    assert summary.event_count == len(sample_session)
    assert summary.tools_used["calculator"] == 2
    assert summary.error_count == 1
    assert summary.policy_failures == [
        {
            "policy": "pii_redaction",
            "action": "send_to_llm",
            "reason": "Contains SSN",
        }
    ]
    assert summary.total_latency_ms == pytest.approx(16.0)


def test_summarise_empty_raises():
    with pytest.raises(ValueError):
        DeterministicReflector().summarise_session([])


def test_synthesise_aggregates_across_sessions(make_event, sample_session):
    extra_session = [
        make_event(session_id="session-2", payload={"goal": "x"}),
        make_event(
            session_id="session-2",
            payload={"tool_name": "web_search"},
        ),
    ]
    # Re-tag the second event as TOOL_CALL so the reflector counts it.
    from trustlayer.schema import EventType

    extra_session[1] = extra_session[1].model_copy(
        update={"event_type": EventType.TOOL_CALL}
    )

    reflector = DeterministicReflector()
    summaries = [
        reflector.summarise_session(sample_session),
        reflector.summarise_session(extra_session),
    ]
    reflection = reflector.synthesise(summaries)
    assert isinstance(reflection, Reflection)
    assert reflection.headline_metrics["sessions"] == 2
    assert reflection.headline_metrics["tool_invocations"] == 3
    assert reflection.headline_metrics["tool_errors"] == 1
    tool_names = [name for name, _ in reflection.top_tools]
    assert "calculator" in tool_names and "web_search" in tool_names
    assert reflection.policy_failures[0]["policy"] == "pii_redaction"
    assert reflection.policy_failures[0]["count"] == 1


def test_synthesise_with_no_failures(make_event):
    from trustlayer.schema import EventType

    events = [
        make_event(event_type=EventType.AGENT_START),
        make_event(event_type=EventType.AGENT_END),
    ]
    reflector = DeterministicReflector()
    summary = reflector.summarise_session(events)
    reflection = reflector.synthesise([summary])
    assert reflection.policy_failures == []
    assert reflection.top_tools == []
    assert reflection.headline_metrics["tool_invocations"] == 0
