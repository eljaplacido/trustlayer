"""Every provider is exercised through `httpx.MockTransport` (§5.3).

No test in this file opens a socket.
"""

from __future__ import annotations

import httpx
import pytest

from trustlayer_eval.models import Message, Residency
from trustlayer_eval.providers import from_env
from trustlayer_eval.providers.agentcenter import AgentcenterProvider
from trustlayer_eval.providers.anthropic import AnthropicProvider
from trustlayer_eval.providers.base import ProviderError, ProviderRefusal
from trustlayer_eval.providers.null import NullProvider
from trustlayer_eval.providers.ollama import OllamaProvider
from trustlayer_eval.providers.openai_compat import OpenAICompatibleProvider

MESSAGES = [Message(role="user", content="hello")]


def test_null_provider_refuses_and_says_how_to_configure() -> None:
    """The default must be a refusal, not a surprise network call."""
    with pytest.raises(ProviderRefusal, match="TRUSTLAYER_EVAL_PROVIDER"):
        NullProvider().complete(MESSAGES)


def test_null_provider_reports_available() -> None:
    """It is working as configured — reporting False would make callers fall
    back to a real provider, the opposite of what an unconfigured install
    should do."""
    assert NullProvider().available() is True


def test_ollama_parses_a_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "m",
                "message": {"content": "hi"},
                "prompt_eval_count": 7,
                "eval_count": 3,
            },
        )
    )
    provider = OllamaProvider(transport=transport)

    response = provider.complete(MESSAGES)

    assert response.text == "hi"
    assert response.tokens_prompt == 7
    assert response.tokens_completion == 3
    assert provider.residency is Residency.LOCAL


def test_ollama_surfaces_an_http_error_as_a_provider_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))

    with pytest.raises(ProviderError):
        OllamaProvider(transport=transport).complete(MESSAGES)


def test_openai_compat_declares_residency_from_config_not_url() -> None:
    """The same protocol serves a local vLLM and a third-country endpoint, so
    the URL cannot tell us where inference happens — only the operator can."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )
    )
    provider = OpenAICompatibleProvider(
        base_url="http://example.invalid",
        model="m",
        residency=Residency.EU,
        transport=transport,
    )

    assert provider.complete(MESSAGES).text == "ok"
    assert provider.residency is Residency.EU


def test_openai_compat_rejects_a_response_with_no_choices() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"model": "m", "choices": []})
    )
    provider = OpenAICompatibleProvider(
        base_url="http://example.invalid", model="m", transport=transport
    )

    with pytest.raises(ProviderError, match="no choices"):
        provider.complete(MESSAGES)


def test_agentcenter_treats_an_in_band_adapter_error_as_a_failure() -> None:
    """The gateway reports adapter failures as `[error: ...]` text with HTTP
    200 — a transport-level check alone would call that a success."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"text": "\n[error: RuntimeError: no such model]", "metrics": {}},
        )
    )
    provider = AgentcenterProvider(transport=transport)

    with pytest.raises(ProviderError, match="adapter error"):
        provider.complete(MESSAGES)


def test_agentcenter_availability_probes_models_not_health() -> None:
    """agentcenter's health route answers while its DuckDB is unusable."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(500)

    provider = AgentcenterProvider(transport=httpx.MockTransport(handler))

    assert provider.available() is False
    assert seen == ["/models"]


def test_anthropic_omits_temperature_on_models_that_reject_it() -> None:
    """`temperature` is removed on current Claude models and returns a 400.

    The `ChatProvider` protocol carries a temperature because local backends
    need one, so this provider must drop it rather than forward it into a
    rejected request.
    """
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.update(_json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "claude-opus-5",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 6},
            },
        )

    provider = AnthropicProvider(
        api_key="test-key", model="claude-opus-5", transport=httpx.MockTransport(handler)
    )

    response = provider.complete(MESSAGES, temperature=0.7)

    assert "temperature" not in captured
    assert response.text == "ok"
    assert response.tokens_prompt == 5


def test_anthropic_sends_the_system_turn_as_a_top_level_field() -> None:
    """The Messages API carries `system` outside `messages`."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.update(_json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "claude-opus-5",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    provider = AnthropicProvider(api_key="k", transport=httpx.MockTransport(handler))
    provider.complete(
        [Message(role="system", content="be terse"), Message(role="user", content="hi")]
    )

    assert captured["system"] == "be terse"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def test_anthropic_treats_a_refusal_as_an_error_not_an_empty_answer() -> None:
    """A safety refusal is HTTP 200 with `stop_reason: refusal`. Reading
    content without checking turns it into a silently empty result."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "claude-opus-5",
                "content": [],
                "stop_reason": "refusal",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
        )
    )
    provider = AnthropicProvider(api_key="k", transport=transport)

    with pytest.raises(ProviderError, match="refused"):
        provider.complete(MESSAGES)


def test_anthropic_residency_is_third_country() -> None:
    assert AnthropicProvider(api_key="k").residency is Residency.THIRD_COUNTRY


def test_from_env_defaults_to_null(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRUSTLAYER_EVAL_PROVIDER", raising=False)

    assert from_env().name == "null"


def test_from_env_rejects_an_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTLAYER_EVAL_PROVIDER", "definitely-not-a-provider")

    with pytest.raises(ProviderError, match="unknown provider"):
        from_env()


def test_openai_compat_requires_an_explicit_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTLAYER_EVAL_PROVIDER", "openai_compat")
    monkeypatch.delenv("TRUSTLAYER_EVAL_BASE_URL", raising=False)

    with pytest.raises(ProviderError, match="BASE_URL"):
        from_env()
