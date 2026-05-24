import json

import httpx
import pytest

from trustlayer import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
    GuardianClient,
)


def _event() -> AgentTraceEvent:
    return AgentTraceEvent(
        agent_id="researcher-1",
        session_id="S1",
        event_type=EventType.TOOL_CALL,
        cynefin_domain=CynefinDomain.COMPLEX,
        payload={"tool_name": "external_llm", "tool_args": {"prompt": "hi"}},
    )


def _make_client(
    handler,
    *,
    fail_open: bool = True,
    policy_name: str | None = None,
) -> GuardianClient:
    return GuardianClient(
        transport=httpx.MockTransport(handler),
        fail_open=fail_open,
        policy_name=policy_name,
    )


def test_check_sends_event_and_returns_verdict() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "decision": "FAIL",
                "rule": "block_external_llm",
                "reason": "PII",
                "policy": "default",
            },
        )

    client = _make_client(handler, policy_name="default")
    verdict = client.check(_event())

    assert verdict["decision"] == "FAIL"
    assert verdict["rule"] == "block_external_llm"
    assert verdict["policy"] == "default"

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["policy_name"] == "default"
    assert body["event"]["agent_id"] == "researcher-1"
    assert body["event"]["payload"]["tool_name"] == "external_llm"


def test_explicit_policy_name_overrides_client_default() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"decision": "PASS", "rule": None, "reason": None, "policy": "ad-hoc"},
        )

    client = _make_client(handler, policy_name="default")
    client.check(_event(), policy_name="ad-hoc")
    assert captured["body"]["policy_name"] == "ad-hoc"  # type: ignore[index]


def test_fail_open_returns_pass_on_transport_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _make_client(handler, fail_open=True)
    verdict = client.check(_event())
    assert verdict["decision"] == "PASS"
    assert verdict["policy"] == "fallback"
    assert "connection refused" in (verdict["reason"] or "")


def test_fail_closed_returns_fail_on_transport_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _make_client(handler, fail_open=False)
    verdict = client.check(_event())
    assert verdict["decision"] == "FAIL"
    assert verdict["policy"] == "fallback"


def test_5xx_response_uses_fallback_verdict() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = _make_client(handler, fail_open=True)
    verdict = client.check(_event())
    assert verdict["decision"] == "PASS"
    assert verdict["policy"] == "fallback"


def test_unexpected_decision_value_triggers_fallback() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"decision": "MAYBE", "rule": None, "reason": None, "policy": "x"},
        )

    client = _make_client(handler, fail_open=True)
    verdict = client.check(_event())
    assert verdict["decision"] == "PASS"  # fail-open fallback
    assert verdict["policy"] == "fallback"


def test_pass_verdict_returns_clean_struct() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "decision": "PASS",
                "rule": "allow_calculator",
                "reason": None,
                "policy": "default",
            },
        )

    client = _make_client(handler)
    verdict = client.check(_event())
    assert verdict["decision"] == "PASS"
    assert verdict["rule"] == "allow_calculator"
    assert verdict["reason"] is None
    assert verdict["policy"] == "default"


def test_context_manager_closes() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"decision": "PASS", "rule": None, "reason": None, "policy": "p"},
        )

    with GuardianClient(transport=httpx.MockTransport(handler)) as client:
        client.check(_event())


def _capture_auth(captured: list[dict], **kwargs: object) -> GuardianClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"headers": dict(request.headers)})
        return httpx.Response(
            200,
            json={"decision": "PASS", "rule": None, "reason": None, "policy": "p"},
        )

    return GuardianClient(transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]


def test_guardian_token_falls_back_to_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTLAYER_API_TOKEN", "guard-env")
    captured: list[dict] = []
    client = _capture_auth(captured)
    client.check(_event())
    assert captured[0]["headers"]["authorization"] == "Bearer guard-env"


def test_guardian_explicit_token_overrides_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUSTLAYER_API_TOKEN", "guard-env")
    captured: list[dict] = []
    client = _capture_auth(captured, api_key="explicit-guard")
    client.check(_event())
    assert captured[0]["headers"]["authorization"] == "Bearer explicit-guard"


def test_guardian_no_token_means_no_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRUSTLAYER_API_TOKEN", raising=False)
    captured: list[dict] = []
    client = _capture_auth(captured)
    client.check(_event())
    assert "authorization" not in captured[0]["headers"]
