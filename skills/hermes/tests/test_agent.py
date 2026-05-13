from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.hermes_agent import HermesAgent
from trustlayer.schema import EventType


def test_ingest_writes_per_session_note(tmp_path: Path, sample_session):
    agent = HermesAgent(tmp_path)
    notes = agent.ingest(sample_session)
    assert len(notes) == 1
    note_path = notes[0]
    assert note_path.exists()
    assert note_path.relative_to(tmp_path) == Path(
        "03_Memory_Traces/researcher/session-1.md"
    )
    body = note_path.read_text(encoding="utf-8")
    assert "# Session `session-1`" in body
    assert "AGENT_START" in body and "AGENT_END" in body


def test_ingest_idempotent_on_trace_id(tmp_path: Path, sample_session):
    agent = HermesAgent(tmp_path)
    agent.ingest(sample_session)
    agent.ingest(sample_session)  # same events again
    cached = agent.session_events("researcher", "session-1")
    assert len(cached) == len(sample_session)


def test_ingest_accepts_dict_and_json_string(tmp_path: Path, sample_session):
    agent = HermesAgent(tmp_path)
    mixed: list = []
    for i, evt in enumerate(sample_session):
        if i % 3 == 0:
            mixed.append(evt)
        elif i % 3 == 1:
            mixed.append(json.loads(evt.model_dump_json()))
        else:
            mixed.append(evt.model_dump_json())
    notes = agent.ingest(mixed)
    assert len(notes) == 1
    assert agent.session_events("researcher", "session-1")  # cache populated


def test_ingest_separates_sessions(tmp_path: Path, make_event):
    a1 = make_event(agent_id="alpha", session_id="s1", event_type=EventType.AGENT_START)
    a2 = make_event(agent_id="alpha", session_id="s2", event_type=EventType.AGENT_START)
    b1 = make_event(agent_id="beta", session_id="s1", event_type=EventType.AGENT_START)
    notes = HermesAgent(tmp_path).ingest([a1, a2, b1])
    assert len(notes) == 3
    rel = sorted(p.relative_to(tmp_path).as_posix() for p in notes)
    assert rel == [
        "03_Memory_Traces/alpha/s1.md",
        "03_Memory_Traces/alpha/s2.md",
        "03_Memory_Traces/beta/s1.md",
    ]


def test_ingest_jsonl_round_trip(tmp_path: Path, sample_session):
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        "\n".join(e.model_dump_json() for e in sample_session) + "\n",
        encoding="utf-8",
    )
    agent = HermesAgent(tmp_path / "vault")
    notes = agent.ingest_jsonl(feed)
    assert len(notes) == 1
    assert notes[0].read_text(encoding="utf-8")


def test_reflect_writes_reflection_note(tmp_path: Path, sample_session, make_event):
    second = [
        make_event(session_id="session-2", event_type=EventType.AGENT_START),
        make_event(session_id="session-2", event_type=EventType.AGENT_END),
    ]
    agent = HermesAgent(tmp_path)
    agent.ingest(sample_session + second)
    reflection_path = agent.reflect()
    assert reflection_path is not None
    body = reflection_path.read_text(encoding="utf-8")
    assert "# Reflection" in body
    assert "[[03_Memory_Traces/researcher/session-1]]" in body
    assert "[[03_Memory_Traces/researcher/session-2]]" in body


def test_reflect_returns_none_when_empty(tmp_path: Path):
    agent = HermesAgent(tmp_path)
    assert agent.reflect() is None


def test_unknown_field_in_jsonl_raises(tmp_path: Path):
    feed = tmp_path / "bad.jsonl"
    feed.write_text(
        json.dumps(
            {
                "agent_id": "a",
                "session_id": "s",
                "event_type": "AGENT_START",
                "rogue": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    agent = HermesAgent(tmp_path / "vault")
    with pytest.raises(Exception):
        agent.ingest_jsonl(feed)
