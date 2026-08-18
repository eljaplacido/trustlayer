"""agentcenter and Ollama do not share a model-id namespace.

agentcenter multiplexes several runtimes, so its ids are runtime-qualified
(`ollama:<tag>`, `vllm:<path>`). Configuring a bare Ollama tag against the
gateway is the most likely mistake, and its raw answer is an opaque 400.
"""

from __future__ import annotations

import httpx
import pytest

from trustlayer_eval.models import Message
from trustlayer_eval.providers import _as_ollama_tag, from_env
from trustlayer_eval.providers.agentcenter import DEFAULT_MODEL, AgentcenterProvider
from trustlayer_eval.providers.base import ProviderError

MESSAGES = [Message(role="user", content="hi")]

REGISTERED = [
    {"id": "ollama:nemotron-3-nano:30b-a3b-q4_K_M", "runtime": "ollama"},
    {"id": "vllm:llamacpp27:/models/Qwen3.6-27B.gguf", "runtime": "vllm"},
]


def test_the_default_agentcenter_model_is_runtime_qualified() -> None:
    assert DEFAULT_MODEL.startswith("ollama:")


def test_an_unqualified_model_id_produces_an_actionable_error() -> None:
    """A bare 400 tells the operator nothing. Name the ids the gateway takes."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            return httpx.Response(200, json=REGISTERED)
        return httpx.Response(400, text="unknown model")

    provider = AgentcenterProvider(
        model="nemotron-3-nano:30b-a3b-q4_K_M", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ProviderError) as caught:
        provider.complete(MESSAGES)

    message = str(caught.value)
    assert "runtime-qualified" in message
    assert "ollama:nemotron-3-nano:30b-a3b-q4_K_M" in message


def test_a_400_for_a_known_model_is_not_relabelled() -> None:
    """Only a model-id mismatch gets the rewrite; other 400s pass through, so a
    different bug is not mislabelled as a configuration error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            return httpx.Response(200, json=REGISTERED)
        return httpx.Response(400, text="malformed request")

    provider = AgentcenterProvider(
        model="ollama:nemotron-3-nano:30b-a3b-q4_K_M", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ProviderError) as caught:
        provider.complete(MESSAGES)

    assert "runtime-qualified" not in str(caught.value)


def test_the_ollama_fallback_strips_the_gateway_prefix() -> None:
    assert _as_ollama_tag("ollama:qwen2.5:7b-instruct") == "qwen2.5:7b-instruct"


def test_a_bare_tag_is_left_alone() -> None:
    assert _as_ollama_tag("qwen2.5:7b-instruct") == "qwen2.5:7b-instruct"


def test_a_vllm_id_is_not_rewritten_into_an_ollama_tag() -> None:
    """Ollama does not serve it, so the fallback should fail loudly rather than
    quietly answer with a different model."""
    assert _as_ollama_tag("vllm:llamacpp27:/models/x.gguf") == "vllm:llamacpp27:/models/x.gguf"


def test_from_env_falls_back_to_ollama_when_the_gateway_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Narrow by design: both are local runtimes, so the fallback cannot change
    the run's residency."""
    monkeypatch.setenv("TRUSTLAYER_EVAL_PROVIDER", "agentcenter")
    # Unroutable port so `available()` fails fast without a real gateway.
    monkeypatch.setenv("TRUSTLAYER_EVAL_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("TRUSTLAYER_EVAL_MODEL", "ollama:qwen2.5:7b-instruct")

    provider = from_env()

    assert provider.name == "ollama"
    assert provider.model == "qwen2.5:7b-instruct"
    assert provider.residency.value == "local"
