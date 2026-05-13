import json

import httpx
import pytest

from trustlayer import Tracer, TrustLayerClient, instrument_tool


def _capture_client(captured: list[dict]) -> TrustLayerClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(202)

    return TrustLayerClient(transport=httpx.MockTransport(handler))


def test_instrument_tool_decorator_emits_pair() -> None:
    captured: list[dict] = []
    tracer = Tracer(agent_id="a", session_id="s", client=_capture_client(captured))

    @instrument_tool(tracer, tool_name="add")
    def add(x: int, y: int) -> int:
        return x + y

    assert add(2, 3) == 5
    assert [e["event_type"] for e in captured] == ["TOOL_CALL", "TOOL_RESULT"]
    assert captured[0]["payload"]["tool_args"]["args"] == [2, 3]
    assert captured[1]["payload"]["result"] == 5


def test_instrument_tool_records_exception() -> None:
    captured: list[dict] = []
    tracer = Tracer(agent_id="a", session_id="s", client=_capture_client(captured))

    @instrument_tool(tracer)
    def will_fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        will_fail()
    assert captured[-1]["payload"]["tool_name"] == "will_fail"
    assert "RuntimeError" in captured[-1]["payload"]["error"]
