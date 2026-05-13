from __future__ import annotations

from hermes.reflector import DeterministicReflector
from hermes.render import render_reflection_note, render_session_note


def test_render_session_note_has_frontmatter_and_timeline(sample_session):
    note = render_session_note(sample_session)
    assert note.startswith("---\n")
    assert "agent_id: researcher" in note
    assert "session_id: session-1" in note
    assert f"event_count: {len(sample_session)}" in note
    assert "## Timeline" in note
    assert "`TOOL_CALL`" in note
    assert "`POLICY_CHECK`" in note
    assert "latency 12.0 ms" in note


def test_render_session_note_empty():
    assert render_session_note([]) == ""


def test_render_reflection_note_links_back_to_sessions(sample_session, make_event):
    from trustlayer.schema import EventType

    second = [
        make_event(session_id="session-2", event_type=EventType.AGENT_START),
        make_event(session_id="session-2", event_type=EventType.AGENT_END),
    ]
    reflector = DeterministicReflector()
    summaries = [
        reflector.summarise_session(sample_session),
        reflector.summarise_session(second),
    ]
    note = render_reflection_note(reflector.synthesise(summaries), summaries)
    assert "# Reflection" in note
    assert "## Headline metrics" in note
    assert "[[03_Memory_Traces/researcher/session-1]]" in note
    assert "[[03_Memory_Traces/researcher/session-2]]" in note
    assert "## Most-used tools" in note
    assert "## Policy failures" in note
    assert "`calculator` x 2" in note


def test_render_session_note_sanitises_unsafe_filenames(make_event):
    from trustlayer.schema import EventType

    events = [
        make_event(
            agent_id="agent/with:slashes",
            session_id="weird id",
            event_type=EventType.AGENT_START,
        ),
    ]
    note = render_session_note(events)
    # Frontmatter quotes the agent_id because it contains a colon.
    assert '"agent/with:slashes"' in note
