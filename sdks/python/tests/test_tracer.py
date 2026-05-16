import json

import httpx
import pytest

from trustlayer import GuardianClient, PolicyCheckResult, Tracer, TrustLayerClient


def _capture_client(captured: list[dict]) -> TrustLayerClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(202)

    return TrustLayerClient(transport=httpx.MockTransport(handler))


def test_tracer_emits_call_and_result() -> None:
    captured: list[dict] = []
    tracer = Tracer(agent_id="a", session_id="s", client=_capture_client(captured))
    with tracer.tool_call("calc", {"x": 1}) as out:
        out["value"] = 42
    assert [e["event_type"] for e in captured] == ["TOOL_CALL", "TOOL_RESULT"]
    assert captured[0]["payload"]["tool_args"] == {"x": 1}
    assert captured[1]["payload"]["result"] == 42
    assert captured[1]["metrics"]["latency_ms"] is not None


def test_tracer_records_error_and_reraises() -> None:
    captured: list[dict] = []
    tracer = Tracer(agent_id="a", session_id="s", client=_capture_client(captured))
    with pytest.raises(ValueError):
        with tracer.tool_call("boom"):
            raise ValueError("nope")
    assert captured[-1]["event_type"] == "TOOL_RESULT"
    assert "ValueError" in captured[-1]["payload"]["error"]
    assert captured[-1]["payload"].get("result") is None


def test_policy_check_emitted() -> None:
    captured: list[dict] = []
    tracer = Tracer(agent_id="a", session_id="s", client=_capture_client(captured))
    tracer.policy_check(
        "pii_redaction",
        action="send_to_llm",
        result=PolicyCheckResult.FAIL,
        reason="Contains SSN",
    )
    assert captured[0]["event_type"] == "POLICY_CHECK"
    assert captured[0]["payload"]["result"] == "FAIL"


def test_tracer_default_session_id_is_unique() -> None:
    a = Tracer(agent_id="x", client=_capture_client([]))
    b = Tracer(agent_id="x", client=_capture_client([]))
    assert a.session_id != b.session_id


def _guardian(decision: str, **extra: object) -> GuardianClient:
    body = {
        "decision": decision,
        "rule": extra.get("rule"),
        "reason": extra.get("reason"),
        "policy": extra.get("policy", "default"),
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return GuardianClient(
        transport=httpx.MockTransport(handler), policy_name="default"
    )


def test_check_emits_tool_call_then_policy_check_and_returns_verdict() -> None:
    captured: list[dict] = []
    tracer = Tracer(agent_id="a", session_id="s", client=_capture_client(captured))
    verdict = tracer.check(
        "external_llm",
        {"prompt": "hi"},
        guardian=_guardian("FAIL", rule="block_external_llm", reason="PII"),
    )

    assert verdict["decision"] == "FAIL"
    assert verdict["rule"] == "block_external_llm"
    assert [e["event_type"] for e in captured] == ["TOOL_CALL", "POLICY_CHECK"]
    assert captured[0]["payload"]["tool_name"] == "external_llm"
    assert captured[1]["payload"]["result"] == "FAIL"
    assert captured[1]["payload"]["action"] == "invoke external_llm"
    assert captured[1]["payload"]["reason"] == "PII"


def test_check_pass_records_pass_in_policy_event() -> None:
    captured: list[dict] = []
    tracer = Tracer(agent_id="a", session_id="s", client=_capture_client(captured))
    verdict = tracer.check(
        "calculator",
        {"x": 1},
        guardian=_guardian("PASS", rule="allow_calculator"),
    )

    assert verdict["decision"] == "PASS"
    assert captured[1]["payload"]["result"] == "PASS"


def test_check_overrides_cynefin_domain_on_emitted_event() -> None:
    captured: list[dict] = []
    tracer = Tracer(agent_id="a", session_id="s", client=_capture_client(captured))
    tracer.check(
        "human_callout",
        {},
        guardian=_guardian("ESCALATE", rule="escalate_complex"),
        cynefin_domain=None,  # falls back to tracer default
    )
    # Default tracer domain is DISORDER unless overridden.
    assert captured[0]["cynefin_domain"] == "DISORDER"


def test_check_forwards_explicit_policy_name_to_guardian() -> None:
    captured_requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"decision": "PASS", "rule": None, "reason": None, "policy": "alt"},
        )

    guardian = GuardianClient(
        transport=httpx.MockTransport(handler), policy_name="default"
    )
    tracer = Tracer(agent_id="a", session_id="s", client=_capture_client([]))
    tracer.check("calc", {}, guardian=guardian, policy_name="alt")
    assert captured_requests[0]["policy_name"] == "alt"
