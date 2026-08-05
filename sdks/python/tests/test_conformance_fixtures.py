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
from pathlib import Path

import pydantic
import pytest

from trustlayer import AgentTraceEvent

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
