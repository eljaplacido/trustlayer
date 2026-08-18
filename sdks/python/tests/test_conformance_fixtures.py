"""Every v0.1 conformance fixture MUST parse under this SDK's strict envelope.

`spec/v0.1/fixtures/` holds deterministic artifacts that every conforming
implementation has to accept (spec §6.2). The reference Rust core already
globs the directory from `core-rs/tests/cross_language.rs`; Phase 8's
engineering contract (`docs/PHASE-8-DESIGN.md` §5.3) extends that rule to
all four SDKs, because a fixture only proves cross-language parity if more
than one language reads it.

Globbing rather than naming files means a fixture added to the spec is
covered here the moment it is committed — the same property that makes the
Rust test resistant to the drift that produced gap G0.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pydantic
import pytest

from trustlayer import AgentTraceEvent, EventType

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "spec" / "v0.1" / "fixtures"

FIXTURES = sorted(FIXTURE_DIR.glob("event-*.json"))


def test_fixture_directory_is_populated() -> None:
    """Guard the glob itself — a bad path would silently skip every case below."""
    assert FIXTURES, f"no event fixtures found under {FIXTURE_DIR}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.stem)
def test_fixture_parses_under_the_strict_envelope(fixture: Path) -> None:
    event = AgentTraceEvent.model_validate_json(fixture.read_text(encoding="utf-8"))

    assert event.agent_id, "agent_id is required by spec §1.2"
    assert event.session_id, "session_id is required by spec §1.2"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.stem)
def test_fixture_round_trip_is_stable(fixture: Path) -> None:
    """Parse -> serialise -> parse must be a fixed point.

    This is what makes a fixture citable across spec versions: an SDK that
    re-emits an event differently each pass cannot be used to demonstrate
    wire-format parity.
    """
    once = AgentTraceEvent.model_validate_json(fixture.read_text(encoding="utf-8"))
    twice = AgentTraceEvent.model_validate_json(once.model_dump_json())

    assert once.model_dump_json() == twice.model_dump_json()


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.stem)
def test_fixture_preserves_envelope_fields(fixture: Path) -> None:
    """Nothing in the envelope is dropped or rewritten on the way through."""
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    event = AgentTraceEvent.model_validate(raw)

    assert str(event.trace_id) == raw["trace_id"]
    assert event.agent_id == raw["agent_id"]
    assert event.session_id == raw["session_id"]
    assert event.event_type.value == raw["event_type"]
    assert event.cynefin_domain.value == raw["cynefin_domain"]
    assert event.payload == raw["payload"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.stem)
def test_fixture_rejects_an_unknown_envelope_field(fixture: Path) -> None:
    """W1 strictness (spec §6.2) is asserted against real fixture data.

    The positive cases above pass just as well under a lenient parser, so
    without this the suite would not actually prove strictness.
    """
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    raw["definitely_not_in_v0_1"] = True

    with pytest.raises(pydantic.ValidationError):
        AgentTraceEvent.model_validate(raw)


def test_absent_parent_trace_id_parses_as_none() -> None:
    """Absent means *unknown*, never *no parent* (spec §1.3).

    Every v0.1 fixture predates the field, so this also proves the addition is
    backwards compatible in the direction that matters: old wire, new parser.
    """
    event = AgentTraceEvent.model_validate_json(
        (FIXTURE_DIR / "event-canonical-go.json").read_text(encoding="utf-8")
    )

    assert event.parent_trace_id is None


def test_parent_trace_id_round_trips_when_present() -> None:
    event = AgentTraceEvent.model_validate_json(
        (FIXTURE_DIR / "event-delegated-go.json").read_text(encoding="utf-8")
    )

    assert str(event.parent_trace_id) == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_unset_parent_trace_id_is_not_serialised() -> None:
    """New emitter, old reader — the direction that actually breaks.

    The envelope is closed (spec §1.2), so a collector built before
    ``parent_trace_id`` existed rejects the whole event if the key is present,
    even as null. Emitting ``"parent_trace_id": null`` therefore turns a MINOR
    addition (§1.7) into a hard break against every collector not yet
    redeployed — which is exactly what a running v0.1 guardian did, returning
    422 for every event this SDK sent.

    Go asserts this same property in ``TestParentTraceIDIsOmittedWhenUnset``;
    the Python SDK only ever tested the old-wire/new-parser direction, so
    nothing here failed when the bytes changed.
    """
    event = AgentTraceEvent(agent_id="a", session_id="s", event_type=EventType.TOOL_CALL)

    assert "parent_trace_id" not in event.model_dump()
    assert "parent_trace_id" not in event.model_dump(mode="json")
    assert "parent_trace_id" not in json.loads(event.model_dump_json())


def test_set_parent_trace_id_is_still_serialised() -> None:
    """Omission must be conditional on absence, not unconditional."""
    parent = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    event = AgentTraceEvent(
        agent_id="a",
        session_id="s",
        event_type=EventType.TOOL_CALL,
        parent_trace_id=parent,
    )

    assert event.model_dump(mode="json")["parent_trace_id"] == str(parent)
