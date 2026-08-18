"""Anthropic Messages API provider (ADR-020 §2).

Spoken to over raw HTTP rather than through the `anthropic` SDK. That is a
deliberate ADR-020 decision — "no provider SDK is vendored" — so that
`requirements-release.txt` and the `pip-audit` surface stay small. The
trade is that the wire contract below is maintained by hand.

Residency is THIRD_COUNTRY by default: this is a US-operated API, and the
egress policy must treat it as such regardless of how convenient it is.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from ..models import Message, ProviderResponse, Residency
from .base import HTTPProvider, ProviderError, merge_system, schema_instruction

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-opus-5"
API_VERSION = "2023-06-01"

#: Sampling parameters were removed from the current Claude models: sending
#: `temperature`, `top_p`, or `top_k` to Opus 5, Sonnet 5, Fable 5, Opus 4.8 or
#: Opus 4.7 is a 400, not a soft ignore. The `ChatProvider` protocol takes a
#: `temperature` because local backends need one, so this provider drops it
#: rather than forwarding it into a rejected request. Determinism on these
#: models comes from the prompt and from `effort`, never from a sampler.
_MODELS_WITHOUT_SAMPLING = (
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)


class _Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class _ContentBlock(BaseModel):
    type: str = ""
    text: str | None = None


class _MessagesResponse(BaseModel):
    """Parsed at the boundary — `dict[str, Any]` stops here (§5.2)."""

    model: str = ""
    content: list[_ContentBlock] = []
    stop_reason: str | None = None
    usage: _Usage = _Usage()


class AnthropicProvider(HTTPProvider):
    name = "anthropic"
    residency = Residency.THIRD_COUNTRY

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        resolved = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        super().__init__(base_url=base_url, model=model, timeout=timeout, transport=transport)
        # Anthropic authenticates with `x-api-key`, not the bearer header the
        # base class installs for OpenAI-compatible backends.
        self._client.headers.pop("Authorization", None)
        self._client.headers["anthropic-version"] = API_VERSION
        if resolved:
            self._client.headers["x-api-key"] = resolved
        self._authenticated = bool(resolved)

    def complete(
        self,
        messages: Sequence[Message],
        *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        if not self._authenticated:
            raise ProviderError("anthropic: no API key (set ANTHROPIC_API_KEY)")

        # The Messages API carries the system prompt as a top-level field, not
        # as a message with role "system".
        system, rest = merge_system(messages)
        wire = [m.as_wire() for m in rest]
        if schema is not None and wire:
            last = wire[-1]
            last["content"] = f"{last['content']}{schema_instruction(schema)}"

        body: dict[str, Any] = {
            "model": self.model,
            # Required by the API, and not a soft hint: generation stops here.
            # Generous because a truncated evaluator answer is indistinguishable
            # from a short one once it reaches the grounding validator.
            "max_tokens": max_tokens if max_tokens is not None else 8192,
            "messages": wire,
        }
        if system:
            body["system"] = system
        if temperature and not self._sampling_removed():
            body["temperature"] = temperature
        # `seed` has no equivalent on this API. Reproducibility comes from the
        # recorded prompt hash instead (ADR-020 §2).

        response = self._post("/v1/messages", body)
        try:
            parsed = _MessagesResponse.model_validate(response.json())
        except (ValidationError, json.JSONDecodeError) as exc:
            raise ProviderError(f"anthropic: unparseable response: {exc}") from exc

        # A safety refusal arrives as HTTP 200 with `stop_reason: "refusal"` and
        # empty or partial content. Reading `content[0]` without this check turns
        # a refusal into an empty finding rather than a recorded refusal.
        if parsed.stop_reason == "refusal":
            raise ProviderError("anthropic: request refused by the model's safety classifiers")

        text = "".join(b.text or "" for b in parsed.content if b.type == "text")
        return ProviderResponse(
            text=text,
            model=parsed.model or self.model,
            tokens_prompt=parsed.usage.input_tokens,
            tokens_completion=parsed.usage.output_tokens,
            raw_finish_reason=parsed.stop_reason,
        )

    def _sampling_removed(self) -> bool:
        return any(self.model.startswith(prefix) for prefix in _MODELS_WITHOUT_SAMPLING)

    def available(self) -> bool:
        """Credential presence only — no probe request.

        Every call to this API costs money and counts against a rate limit, so
        a reachability check that bills the operator to answer "probably" is
        the wrong trade. A misconfigured key surfaces on first real use.
        """
        return self._authenticated
