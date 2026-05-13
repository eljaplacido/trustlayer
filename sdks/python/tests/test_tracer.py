import json

import httpx
import pytest

from trustlayer import PolicyCheckResult, Tracer, TrustLayerClient


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
