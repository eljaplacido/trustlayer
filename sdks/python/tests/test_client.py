import json

import httpx
import pytest

from trustlayer import AgentTraceEvent, EventType, TrustLayerClient


def _make_client(captured: list[dict]) -> TrustLayerClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "headers": dict(request.headers),
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(202)

    return TrustLayerClient(api_key="secret", transport=httpx.MockTransport(handler))


def test_emit_sends_event_with_auth_header() -> None:
    captured: list[dict] = []
    client = _make_client(captured)
    event = AgentTraceEvent(
        agent_id="a", session_id="s", event_type=EventType.AGENT_START
    )
    client.emit(event)
    assert captured[0]["body"]["agent_id"] == "a"
    assert captured[0]["headers"]["authorization"] == "Bearer secret"
    assert captured[0]["headers"]["content-type"] == "application/json"


def test_emit_batch_sends_array() -> None:
    captured: list[dict] = []
    client = _make_client(captured)
    events = [
        AgentTraceEvent(agent_id="a", session_id="s", event_type=EventType.AGENT_START),
        AgentTraceEvent(agent_id="a", session_id="s", event_type=EventType.AGENT_END),
    ]
    client.emit_batch(events)
    assert isinstance(captured[0]["body"], list)
    assert len(captured[0]["body"]) == 2
    assert captured[0]["body"][1]["event_type"] == "AGENT_END"


def test_emit_swallows_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = TrustLayerClient(transport=httpx.MockTransport(handler))
    event = AgentTraceEvent(
        agent_id="a", session_id="s", event_type=EventType.AGENT_START
    )
    # Must not raise: instrumentation never breaks the host agent.
    client.emit(event)


def test_context_manager_closes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    with TrustLayerClient(transport=httpx.MockTransport(handler)) as client:
        client.emit(
            AgentTraceEvent(
                agent_id="a", session_id="s", event_type=EventType.AGENT_START
            )
        )


def _make_token_capture_client(
    captured: list[dict], **kwargs: object
) -> TrustLayerClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"headers": dict(request.headers)})
        return httpx.Response(202)

    return TrustLayerClient(transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]


def test_token_falls_back_to_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTLAYER_API_TOKEN", "from-env")
    captured: list[dict] = []
    client = _make_token_capture_client(captured)
    client.emit(
        AgentTraceEvent(agent_id="a", session_id="s", event_type=EventType.AGENT_START)
    )
    assert captured[0]["headers"]["authorization"] == "Bearer from-env"


def test_explicit_token_overrides_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTLAYER_API_TOKEN", "from-env")
    captured: list[dict] = []
    client = _make_token_capture_client(captured, api_key="explicit")
    client.emit(
        AgentTraceEvent(agent_id="a", session_id="s", event_type=EventType.AGENT_START)
    )
    assert captured[0]["headers"]["authorization"] == "Bearer explicit"


def test_no_token_means_no_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRUSTLAYER_API_TOKEN", raising=False)
    captured: list[dict] = []
    client = _make_token_capture_client(captured)
    client.emit(
        AgentTraceEvent(agent_id="a", session_id="s", event_type=EventType.AGENT_START)
    )
    assert "authorization" not in captured[0]["headers"]
