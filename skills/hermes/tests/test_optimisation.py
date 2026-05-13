"""Tests for the Hermes memory/token optimisations (ADR-003)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.hermes_agent import HermesAgent
from hermes.reflector import DeterministicReflector
from trustlayer.schema import EventType


# -- Payload truncation -------------------------------------------------


def test_payload_strings_are_truncated(tmp_path: Path, make_event):
    big = "X" * 5_000
    evt = make_event(
        event_type=EventType.TOOL_RESULT,
        payload={"tool_name": "leaky", "result": big},
    )
    agent = HermesAgent(tmp_path, max_payload_chars=1_000)
    agent.ingest([evt])
    cached = agent.session_events("researcher", "session-1")[0]
    assert isinstance(cached.payload["result"], str)
    assert len(cached.payload["result"]) < 1_200  # original + small marker
    assert "<...truncated 4000 chars>" in cached.payload["result"]


def test_payload_truncation_recurses_into_nested(tmp_path: Path, make_event):
    big = "Y" * 5_000
    evt = make_event(
        event_type=EventType.TOOL_RESULT,
        payload={
            "tool_name": "t",
            "result": {"nested": {"deep": big}, "list": [big, "small"]},
        },
    )
    agent = HermesAgent(tmp_path, max_payload_chars=500)
    agent.ingest([evt])
    p = agent.session_events("researcher", "session-1")[0].payload
    assert "<...truncated" in p["result"]["nested"]["deep"]
    assert "<...truncated" in p["result"]["list"][0]
    assert p["result"]["list"][1] == "small"  # short strings untouched


def test_max_payload_chars_zero_disables_truncation(tmp_path: Path, make_event):
    big = "Z" * 5_000
    evt = make_event(
        event_type=EventType.TOOL_RESULT,
        payload={"tool_name": "t", "result": big},
    )
    agent = HermesAgent(tmp_path, max_payload_chars=0)
    agent.ingest([evt])
    cached = agent.session_events("researcher", "session-1")[0]
    assert len(cached.payload["result"]) == 5_000
    assert "<...truncated" not in cached.payload["result"]


# -- JSONL sidecar persistence -----------------------------------------


def test_sidecar_records_every_unique_trace_id(tmp_path: Path, sample_session):
    agent = HermesAgent(tmp_path)
    agent.ingest(sample_session)
    sidecar = tmp_path / ".hermes_state/researcher/session-1.events.jsonl"
    assert sidecar.exists()
    lines = [
        json.loads(line)
        for line in sidecar.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == len(sample_session)
    # Re-ingest must NOT duplicate sidecar entries.
    agent.ingest(sample_session)
    lines2 = [
        json.loads(line)
        for line in sidecar.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines2) == len(sample_session)


def test_persist_events_false_skips_sidecar(tmp_path: Path, sample_session):
    agent = HermesAgent(tmp_path, persist_events=False)
    agent.ingest(sample_session)
    assert not (tmp_path / ".hermes_state").exists()


def test_custom_state_path_isolated_from_vault(tmp_path: Path, sample_session):
    state = tmp_path / "external_state"
    agent = HermesAgent(tmp_path / "vault", state_path=state)
    agent.ingest(sample_session)
    assert (state / "researcher/session-1.events.jsonl").exists()
    assert not (tmp_path / "vault/.hermes_state").exists()


# -- LRU eviction -------------------------------------------------------


def test_lru_evicts_oldest_session(tmp_path: Path, make_event):
    agent = HermesAgent(tmp_path, max_cached_sessions=2)
    e1 = make_event(session_id="s1", event_type=EventType.AGENT_START)
    e2 = make_event(session_id="s2", event_type=EventType.AGENT_START)
    e3 = make_event(session_id="s3", event_type=EventType.AGENT_START)
    agent.ingest([e1, e2, e3])
    keys = [k[1] for k in agent.session_keys]
    assert "s1" not in keys
    assert "s2" in keys and "s3" in keys
    # The evicted session's markdown was still flushed before eviction.
    assert (tmp_path / "03_Memory_Traces/researcher/s1.md").exists()


def test_lru_touch_reorders_on_reingest(tmp_path: Path, make_event):
    agent = HermesAgent(tmp_path, max_cached_sessions=2)
    e1 = make_event(session_id="s1", event_type=EventType.AGENT_START)
    e2 = make_event(session_id="s2", event_type=EventType.AGENT_START)
    e3 = make_event(session_id="s3", event_type=EventType.AGENT_START)
    agent.ingest([e1, e2])
    # Re-touching s1 should keep it; s2 becomes the oldest.
    agent.ingest([make_event(session_id="s1", event_type=EventType.TOOL_CALL)])
    agent.ingest([e3])
    keys = [k[1] for k in agent.session_keys]
    assert "s1" in keys
    assert "s2" not in keys


def test_max_cached_sessions_none_disables_eviction(tmp_path: Path, make_event):
    agent = HermesAgent(tmp_path, max_cached_sessions=None)
    for i in range(10):
        agent.ingest(
            [make_event(session_id=f"s{i}", event_type=EventType.AGENT_START)]
        )
    assert len(agent.session_keys) == 10


# -- Rehydration via reflect() -----------------------------------------


def test_reflect_rehydrates_evicted_sessions(tmp_path: Path, make_event):
    agent = HermesAgent(tmp_path, max_cached_sessions=1)
    e1 = [
        make_event(session_id="s1", event_type=EventType.AGENT_START),
        make_event(
            session_id="s1",
            event_type=EventType.TOOL_CALL,
            payload={"tool_name": "calc", "tool_args": {}},
        ),
    ]
    e2 = [make_event(session_id="s2", event_type=EventType.AGENT_START)]
    agent.ingest(e1)
    agent.ingest(e2)  # forces eviction of s1
    assert "s1" not in [k[1] for k in agent.session_keys]
    reflection = agent.reflect()
    assert reflection is not None
    body = reflection.read_text(encoding="utf-8")
    assert "[[03_Memory_Traces/researcher/s1]]" in body
    assert "[[03_Memory_Traces/researcher/s2]]" in body


def test_session_events_falls_back_to_sidecar(tmp_path: Path, sample_session):
    agent = HermesAgent(tmp_path, max_cached_sessions=1)
    agent.ingest(sample_session)
    # Force eviction by ingesting a new session.
    from trustlayer.schema import AgentTraceEvent, EventType, Metrics
    from datetime import datetime, timezone
    from uuid import uuid4

    other = AgentTraceEvent(
        trace_id=uuid4(),
        agent_id="other",
        session_id="x",
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.AGENT_START,
        payload={},
        metrics=Metrics(),
    )
    agent.ingest([other])
    rehydrated = agent.session_events("researcher", "session-1")
    assert len(rehydrated) == len(sample_session)


# -- compact_text -------------------------------------------------------


def test_compact_text_summarises_session(sample_session):
    summary = DeterministicReflector().summarise_session(sample_session)
    text = summary.compact_text()
    assert "researcher/session-1" in text
    assert f"events={summary.event_count}" in text
    assert "tools[calculator=2" in text
    assert "errors=1" in text
    assert "policy_fail[pii_redaction:send_to_llm" in text
    assert "tool_latency=16ms" in text


def test_compact_text_truncated_to_max_chars(sample_session):
    summary = DeterministicReflector().summarise_session(sample_session)
    short = summary.compact_text(max_chars=40)
    assert len(short) == 40
    assert short.endswith("...")


def test_compact_text_no_tools_or_failures(make_event):
    events = [
        make_event(event_type=EventType.AGENT_START),
        make_event(event_type=EventType.AGENT_END),
    ]
    summary = DeterministicReflector().summarise_session(events)
    text = summary.compact_text()
    assert "tools[" not in text
    assert "errors=" not in text
    assert "policy_fail" not in text


# -- End-to-end with all optimisations enabled -------------------------


def test_end_to_end_with_aggressive_caps(tmp_path: Path, make_event):
    # 5 sessions, cache only holds 2; each event payload truncated to 100 chars.
    agent = HermesAgent(
        tmp_path,
        max_payload_chars=100,
        max_cached_sessions=2,
    )
    for i in range(5):
        big_arg = "Q" * 500
        agent.ingest(
            [
                make_event(
                    session_id=f"s{i}",
                    event_type=EventType.TOOL_CALL,
                    payload={"tool_name": "t", "tool_args": {"big": big_arg}},
                )
            ]
        )
    # In-memory has 2 of 5; sidecars have all 5.
    assert len(agent.session_keys) == 2
    sidecar_root = tmp_path / ".hermes_state/researcher"
    assert len(list(sidecar_root.glob("*.events.jsonl"))) == 5
    reflection = agent.reflect()
    assert reflection is not None
    body = reflection.read_text(encoding="utf-8")
    for i in range(5):
        assert f"[[03_Memory_Traces/researcher/s{i}]]" in body
