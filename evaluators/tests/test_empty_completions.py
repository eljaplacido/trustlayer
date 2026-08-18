"""An empty completion is a failure, not an answer.

The local frontier models are reasoning models: the chain of thought is drawn
from the same token budget as the response, so a tight cap produces an empty
`content` with a full `thinking`. Returning "" would hand the evaluator
something unparseable and burn its single retry on a prompt that was never the
problem.
"""

from __future__ import annotations

import httpx
import pytest

from trustlayer_eval.models import Message
from trustlayer_eval.providers.agentcenter import AgentcenterProvider
from trustlayer_eval.providers.base import ProviderError
from trustlayer_eval.providers.ollama import OllamaProvider

MESSAGES = [Message(role="user", content="hi")]


def ollama_response(**message: object) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "m",
                "message": {"role": "assistant", **message},
                "done_reason": message.pop("_done_reason", "stop"),
                "prompt_eval_count": 10,
                "eval_count": 16,
            },
        )
    )


def test_a_thinking_only_response_names_the_token_budget() -> None:
    """The real failure observed against nemotron-3-nano:30b."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "m",
                "message": {"content": "", "thinking": "The user asks me to"},
                "done_reason": "length",
                "eval_count": 16,
            },
        )
    )

    with pytest.raises(ProviderError, match="entire token budget thinking"):
        OllamaProvider(transport=transport).complete(MESSAGES)


def test_an_empty_response_with_no_thinking_reports_the_finish_reason() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"model": "m", "message": {"content": "   "}, "done_reason": "stop"},
        )
    )

    with pytest.raises(ProviderError, match="empty completion"):
        OllamaProvider(transport=transport).complete(MESSAGES)


def test_ollama_asks_for_a_budget_large_enough_to_answer_after_thinking() -> None:
    """Ollama's own default is 128 tokens, which a reasoning model spends
    before it starts answering."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(
            200, json={"model": "m", "message": {"content": "ok"}, "done_reason": "stop"}
        )

    OllamaProvider(transport=httpx.MockTransport(handler)).complete(MESSAGES)

    options = captured["options"]
    assert isinstance(options, dict)
    assert options["num_predict"] >= 4096


def test_agentcenter_rejects_a_silent_empty_completion() -> None:
    """The gateway answers 200 with empty text and zero tokens in this case."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"text": "", "metrics": {"gen_tokens": 0, "ttft_ms": None}},
        )
    )

    with pytest.raises(ProviderError, match="empty completion"):
        AgentcenterProvider(transport=transport).complete(MESSAGES)


def test_a_real_answer_still_passes() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "m",
                "message": {"content": "the answer", "thinking": "some reasoning"},
                "done_reason": "stop",
                "eval_count": 5,
            },
        )
    )

    assert OllamaProvider(transport=transport).complete(MESSAGES).text == "the answer"
