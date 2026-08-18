"""OpenAI-compatible provider — vLLM, LM Studio, OpenRouter, Azure (ADR-020 §2).

Residency is **declared by config**, never inferred. The same wire protocol
serves a vLLM process on this machine and a model in another jurisdiction, so
the endpoint URL cannot tell us where inference happens; only the operator
can, and the egress policy holds them to what they declared.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from ..models import Message, ProviderResponse, Residency
from .base import HTTPProvider, ProviderError, schema_instruction


class _Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _ChoiceMessage(BaseModel):
    content: str | None = ""


class _Choice(BaseModel):
    message: _ChoiceMessage = _ChoiceMessage()
    finish_reason: str | None = None


class _ChatCompletion(BaseModel):
    model: str = ""
    choices: list[_Choice] = []
    usage: _Usage = _Usage()


class OpenAICompatibleProvider(HTTPProvider):
    name = "openai_compat"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        residency: Residency = Residency.UNKNOWN,
        api_key: str | None = None,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            model=model,
            timeout=timeout,
            transport=transport,
            api_key=api_key,
        )
        self.residency = residency

    def complete(
        self,
        messages: Sequence[Message],
        *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        wire = [m.as_wire() for m in messages]
        if schema is not None and wire:
            last = wire[-1]
            last["content"] = f"{last['content']}{schema_instruction(schema)}"

        body: dict[str, Any] = {
            "model": self.model,
            "messages": wire,
            "temperature": temperature,
            "stream": False,
        }
        if seed is not None:
            body["seed"] = seed
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if schema is not None:
            body["response_format"] = {"type": "json_object"}

        response = self._post("/v1/chat/completions", body)
        try:
            parsed = _ChatCompletion.model_validate(response.json())
        except (ValidationError, json.JSONDecodeError) as exc:
            raise ProviderError(f"openai_compat: unparseable response: {exc}") from exc

        if not parsed.choices:
            raise ProviderError("openai_compat: response carried no choices")

        first = parsed.choices[0]
        return ProviderResponse(
            text=first.message.content or "",
            model=parsed.model or self.model,
            tokens_prompt=parsed.usage.prompt_tokens,
            tokens_completion=parsed.usage.completion_tokens,
            raw_finish_reason=first.finish_reason,
        )

    def available(self) -> bool:
        try:
            return self._client.get(f"{self.base_url}/v1/models").status_code < 400
        except httpx.HTTPError:
            return False
