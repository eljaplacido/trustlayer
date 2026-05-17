"""Unit tests for the TrustLayer MCP tool handlers.

These tests exercise the pure handler functions in :mod:`trustlayer_mcp.tools`
without going through the MCP transport. External HTTP clients are stubbed;
Hermes runs against a real tmpdir vault so the file-system semantics are
covered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from trustlayer import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
)

from trustlayer_mcp.tools import (
    EmitEventInput,
    GuardianCheckInput,
    HermesGetSessionInput,
    HermesIngestInput,
    HermesReflectInput,
    emit_event,
    guardian_check,
    hermes_get_session,
    hermes_ingest,
    hermes_reflect,
)


class _FakeIngestClient:
    """Records every emitted event so the test can assert."""

    last_endpoint: str | None = None

    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = endpoint
        _FakeIngestClient.last_endpoint = endpoint
        self.emitted: list[AgentTraceEvent] = []
        self.closed = False

    def emit(self, event: AgentTraceEvent) -> None:
        self.emitted.append(event)

    def close(self) -> None:
        self.closed = True


class _FakeGuardian:
    """Returns a canned verdict and records what was passed in."""

    last_event: AgentTraceEvent | None = None
    last_policy_name: str | None = None
    last_endpoint: str | None = None
    last_fail_open: bool | None = None

    def __init__(
        self,
        endpoint: str,
        *,
        policy_name: str | None,
        fail_open: bool,
        decision: str = "PASS",
    ) -> None:
        _FakeGuardian.last_endpoint = endpoint
        _FakeGuardian.last_policy_name = policy_name
        _FakeGuardian.last_fail_open = fail_open
        self._decision = decision
        self.closed = False

    def check(
        self, event: AgentTraceEvent, policy_name: str | None = None
    ) -> dict[str, Any]:
        _FakeGuardian.last_event = event
        _FakeGuardian.last_policy_name = policy_name or _FakeGuardian.last_policy_name
        return {
            "decision": self._decision,
            "rule": "test_rule",
            "reason": None,
            "policy": policy_name or "default",
        }

    def close(self) -> None:
        self.closed = True


def _event_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trace_id": "11111111-1111-4111-8111-111111111111",
        "agent_id": "researcher-1",
        "session_id": "S1",
        "timestamp": "2026-05-16T10:00:00+00:00",
        "event_type": "TOOL_CALL",
        "cynefin_domain": "COMPLEX",
        "payload": {"tool_name": "external_llm", "tool_args": {"prompt": "hi"}},
        "metrics": {},
    }
    base.update(overrides)
    return base


def test_emit_event_builds_event_and_calls_client() -> None:
    result = emit_event(
        EmitEventInput(
            agent_id="a",
            session_id="s",
            event_type=EventType.TOOL_CALL,
            payload={"tool_name": "calc", "tool_args": {"x": 1}},
            cynefin_domain=CynefinDomain.CLEAR,
            endpoint="http://example/ingest",
        ),
        client_factory=_FakeIngestClient,
    )
    assert result["agent_id"] == "a"
    assert result["event_type"] == "TOOL_CALL"
    assert result["payload"]["tool_name"] == "calc"
    assert _FakeIngestClient.last_endpoint == "http://example/ingest"


def test_emit_event_uses_default_endpoint_when_unset() -> None:
    _FakeIngestClient.last_endpoint = "sentinel"
    emit_event(
        EmitEventInput(
            agent_id="a",
            session_id="s",
            event_type=EventType.AGENT_START,
        ),
        client_factory=_FakeIngestClient,
    )
    assert _FakeIngestClient.last_endpoint is None


def test_guardian_check_returns_verdict_dict() -> None:
    def factory(
        endpoint: str, *, policy_name: str | None, fail_open: bool
    ) -> _FakeGuardian:
        return _FakeGuardian(
            endpoint, policy_name=policy_name, fail_open=fail_open, decision="FAIL"
        )

    verdict = guardian_check(
        GuardianCheckInput(
            event=AgentTraceEvent(**_event_dict()),
            policy_name="strict",
            endpoint="http://example/check",
            fail_open=False,
        ),
        client_factory=factory,
    )
    assert verdict["decision"] == "FAIL"
    assert verdict["policy"] == "strict"
    assert _FakeGuardian.last_event is not None
    assert _FakeGuardian.last_event.agent_id == "researcher-1"
    assert _FakeGuardian.last_endpoint == "http://example/check"
    assert _FakeGuardian.last_fail_open is False


def test_hermes_ingest_writes_session_notes(tmp_path: Path) -> None:
    result = hermes_ingest(
        HermesIngestInput(
            vault_path=str(tmp_path),
            events=[
                _event_dict(),
                _event_dict(
                    trace_id="22222222-2222-4222-8222-222222222222",
                    event_type="TOOL_RESULT",
                    payload={"tool_name": "external_llm", "result": "ok"},
                ),
            ],
        ),
    )
    notes = [Path(p) for p in result["notes_written"]]
    assert len(notes) == 1
    assert notes[0].exists()
    text = notes[0].read_text(encoding="utf-8")
    assert "researcher-1" in text
    assert "TOOL_CALL" in text and "TOOL_RESULT" in text
    assert result["reflection_path"] is None


def test_hermes_ingest_with_reflect_writes_reflection(tmp_path: Path) -> None:
    result = hermes_ingest(
        HermesIngestInput(
            vault_path=str(tmp_path),
            events=[_event_dict()],
            reflect=True,
        ),
    )
    assert result["reflection_path"] is not None
    assert Path(result["reflection_path"]).exists()


def test_hermes_ingest_accepts_jsonl_path(tmp_path: Path) -> None:
    jsonl = tmp_path / "traces.jsonl"
    jsonl.write_text(
        "\n".join(
            [
                json.dumps(_event_dict()),
                json.dumps(
                    _event_dict(
                        trace_id="33333333-3333-4333-8333-333333333333",
                        event_type="POLICY_CHECK",
                        payload={
                            "policy_name": "default",
                            "action": "invoke external_llm",
                            "result": "FAIL",
                            "reason": "PII",
                        },
                    )
                ),
            ]
        ),
        encoding="utf-8",
    )
    result = hermes_ingest(
        HermesIngestInput(
            vault_path=str(tmp_path),
            jsonl_path=str(jsonl),
        ),
    )
    assert result["notes_written"]


def test_hermes_ingest_rejects_both_events_and_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        hermes_ingest(
            HermesIngestInput(
                vault_path=str(tmp_path),
                events=[_event_dict()],
                jsonl_path=str(tmp_path / "x.jsonl"),
            ),
        )


def test_hermes_ingest_rejects_neither(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        hermes_ingest(HermesIngestInput(vault_path=str(tmp_path)))


def test_hermes_get_session_returns_events(tmp_path: Path) -> None:
    hermes_ingest(
        HermesIngestInput(
            vault_path=str(tmp_path),
            events=[
                _event_dict(),
                _event_dict(
                    trace_id="44444444-4444-4444-8444-444444444444",
                    event_type="TOOL_RESULT",
                ),
            ],
        ),
    )
    out = hermes_get_session(
        HermesGetSessionInput(
            vault_path=str(tmp_path),
            agent_id="researcher-1",
            session_id="S1",
        ),
    )
    assert out["agent_id"] == "researcher-1"
    assert out["session_id"] == "S1"
    assert len(out["events"]) == 2
    assert out["events"][0]["event_type"] == "TOOL_CALL"


def test_hermes_get_session_unknown_returns_empty(tmp_path: Path) -> None:
    out = hermes_get_session(
        HermesGetSessionInput(
            vault_path=str(tmp_path),
            agent_id="ghost",
            session_id="none",
        ),
    )
    assert out["events"] == []


def test_hermes_reflect_writes_reflection(tmp_path: Path) -> None:
    hermes_ingest(
        HermesIngestInput(vault_path=str(tmp_path), events=[_event_dict()]),
    )
    out = hermes_reflect(HermesReflectInput(vault_path=str(tmp_path)))
    assert out["reflection_path"] is not None
    assert Path(out["reflection_path"]).exists()


def test_hermes_reflect_on_empty_vault_returns_none(tmp_path: Path) -> None:
    out = hermes_reflect(HermesReflectInput(vault_path=str(tmp_path)))
    assert out["reflection_path"] is None
