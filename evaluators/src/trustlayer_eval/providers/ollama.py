"""Ollama provider — the local default (ADR-020 §2).

Same endpoint shape Hermes has spoken since ADR-013, so the reflector can be
refactored onto this layer without changing what goes over the wire.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from ..models import Message, ProviderResponse, Residency
from .base import HTTPProvider, ProviderError

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "nemotron-3-nano:30b-a3b-q4_K_M"


class _OllamaMessage(BaseModel):
    content: str = ""
    #: Reasoning models (nemotron, deepseek-r1, qwen3) return their chain of
    #: thought here and leave `content` empty until they finish thinking. It is
    #: parsed so an empty answer can say *why* it was empty rather than looking
    #: like the model had nothing to say.
    thinking: str = ""


class _OllamaChatResponse(BaseModel):
    """Parsed at the boundary so no `dict[str, Any]` escapes this module."""

    model: str = ""
    message: _OllamaMessage = _OllamaMessage()
    done_reason: str | None = None
    prompt_eval_count: int = 0
    eval_count: int = 0


class OllamaProvider(HTTPProvider):
    name = "ollama"
    residency = Residency.LOCAL

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, model=model, timeout=timeout, transport=transport)

    def complete(
        self,
        messages: Sequence[Message],
        *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        options: dict[str, Any] = {"temperature": temperature}
        if seed is not None:
            options["seed"] = seed
        # Ollama's own default (128) is far too small here: the local frontier
        # models are reasoning models that draw the chain of thought from this
        # same budget, so leaving it unset yields an empty completion rather
        # than a short one.
        options["num_predict"] = max_tokens if max_tokens is not None else 8192

        body: dict[str, Any] = {
            "model": self.model,
            "messages": [m.as_wire() for m in messages],
            "stream": False,
            "options": options,
        }
        if schema is not None:
            # Ollama takes a JSON Schema directly, which is stronger than
            # asking for JSON in the prompt and hoping.
            body["format"] = schema.model_json_schema()

        response = self._post("/api/chat", body)
        try:
            parsed = _OllamaChatResponse.model_validate(response.json())
        except (ValidationError, json.JSONDecodeError) as exc:
            raise ProviderError(f"ollama: unparseable response: {exc}") from exc

        # An empty completion is a failure, not an answer. Returning "" here
        # would hand the evaluator something unparseable and burn its single
        # retry on a prompt that was never the problem.
        if not parsed.message.content.strip():
            if parsed.done_reason == "length" and parsed.message.thinking:
                raise ProviderError(
                    f"ollama: {self.model} spent its entire token budget thinking and "
                    f"produced no answer. Raise max_tokens — reasoning models need "
                    f"room for the chain of thought *and* the response."
                )
            raise ProviderError(
                f"ollama: {self.model} returned an empty completion "
                f"(done_reason={parsed.done_reason!r})"
            )

        return ProviderResponse(
            text=parsed.message.content,
            model=parsed.model or self.model,
            tokens_prompt=parsed.prompt_eval_count,
            tokens_completion=parsed.eval_count,
            raw_finish_reason=parsed.done_reason,
        )

    def available(self) -> bool:
        try:
            return self._client.get(f"{self.base_url}/api/tags").status_code < 400
        except httpx.HTTPError:
            return False

    def installed_models(self) -> tuple[str, ...]:
        """Model ids this daemon can serve. Powers the dashboard picker."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return ()
        if not isinstance(payload, dict):
            return ()
        models = payload.get("models")
        if not isinstance(models, list):
            return ()
        names: list[str] = []
        for entry in models:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str):
                    names.append(name)
        return tuple(names)
