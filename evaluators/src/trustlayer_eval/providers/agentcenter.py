"""agentcenter gateway provider.

agentcenter is the local model IDE and KPI store on this machine; routing
through it rather than straight at Ollama means every evaluator call is also
recorded in its DuckDB time-series (latency, TTFT, tokens/s), so model choice
for evaluation can be judged on the same evidence as every other local
workload.

It multiplexes several runtimes (Ollama, OpenFang, vLLM, SGLang), so a model
id here is whatever agentcenter registered, not necessarily an Ollama tag.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from ..models import Message, ProviderResponse, Residency
from .base import HTTPProvider, ProviderError, merge_system, schema_instruction

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
#: agentcenter multiplexes several runtimes, so its model ids are
#: runtime-qualified (`ollama:<tag>`, `vllm:<path>`) and are *not* interchangeable
#: with a bare Ollama tag. Getting this wrong is the most likely configuration
#: mistake, so `complete` turns the resulting 400 into an error listing the
#: real ids.
DEFAULT_MODEL = "ollama:nemotron-3-nano:30b-a3b-q4_K_M"


class _PlaygroundMetrics(BaseModel):
    ttft_ms: float | None = None
    gen_tokens: int | None = None
    gen_tok_per_s: float | None = None


class _PlaygroundResponse(BaseModel):
    session_id: str | None = None
    message_id: str | None = None
    text: str = ""
    metrics: _PlaygroundMetrics = _PlaygroundMetrics()


class AgentcenterProvider(HTTPProvider):
    name = "agentcenter"
    residency = Residency.LOCAL
    """LOCAL because agentcenter's own adapters are local runtimes. If it is
    ever configured to proxy a cloud model, that residency belongs on the
    provider entry for *that* backend — this class must not be used to
    launder a third-country endpoint into a LOCAL label."""

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
        # /playground/chat takes a single prompt plus an optional system
        # string rather than a message list, so a multi-turn conversation is
        # flattened. Roles are labelled in the flattened text so the model can
        # still tell who said what.
        system, rest = merge_system(messages)
        prompt = "\n\n".join(
            m.content if m.role == "user" else f"[{m.role}]\n{m.content}" for m in rest
        )
        instruction = schema_instruction(schema)
        if instruction:
            prompt = f"{prompt}{instruction}"

        body: dict[str, Any] = {
            "model_id": self.model,
            "prompt": prompt,
            "system": system,
            "temperature": temperature,
            # Generous because the local frontier models are reasoning models:
            # the chain of thought is drawn from the same budget as the answer,
            # so a tight cap yields an empty completion rather than a short one.
            "max_tokens": max_tokens if max_tokens is not None else 8192,
        }
        if seed is not None:
            body["seed"] = seed

        try:
            response = self._post("/playground/chat", body)
        except ProviderError as exc:
            # The gateway answers an unresolvable model id with a bare 400.
            # Since its ids are runtime-qualified and a bare Ollama tag is the
            # obvious thing to configure, say so and list what it will accept.
            if "400" in str(exc):
                known = self.registered_models()
                if known and self.model not in known:
                    listed = ", ".join(known[:10])
                    raise ProviderError(
                        f"agentcenter does not know model {self.model!r}. Its ids are "
                        f"runtime-qualified (e.g. 'ollama:{self.model}'). Registered: "
                        f"{listed}"
                    ) from exc
            raise

        try:
            parsed = _PlaygroundResponse.model_validate(response.json())
        except (ValidationError, json.JSONDecodeError) as exc:
            raise ProviderError(f"agentcenter: unparseable response: {exc}") from exc

        # The gateway reports adapter failures in-band as `[error: ...]`
        # appended to the text rather than as a non-2xx status, so a
        # transport-level check alone would call a failed generation a success.
        if parsed.text.lstrip().startswith("[error:") or "\n[error:" in parsed.text:
            raise ProviderError(f"agentcenter: adapter error: {parsed.text.strip()[:300]}")

        # The gateway also answers 200 with empty text and zero tokens when the
        # adapter produced nothing — a reasoning model that spent its whole
        # budget thinking is the common cause. Silence is not an answer.
        if not parsed.text.strip():
            raise ProviderError(
                f"agentcenter: {self.model} returned an empty completion "
                f"({parsed.metrics.gen_tokens or 0} tokens). If this is a reasoning "
                f"model, raise max_tokens so it has room to answer after thinking."
            )

        return ProviderResponse(
            text=parsed.text,
            model=self.model,
            tokens_completion=parsed.metrics.gen_tokens or 0,
        )

    def available(self) -> bool:
        """Probe `/models`, not `/health`.

        agentcenter's health route answers while its DuckDB is unusable, and a
        gateway that cannot resolve a model id is not available for our
        purposes even if the process is up.
        """
        try:
            return self._client.get(f"{self.base_url}/models").status_code < 400
        except httpx.HTTPError:
            return False

    def registered_models(self) -> tuple[str, ...]:
        try:
            response = self._client.get(f"{self.base_url}/models")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return ()
        if not isinstance(payload, list):
            return ()
        ids: list[str] = []
        for entry in payload:
            if isinstance(entry, dict):
                value = entry.get("id") or entry.get("model_id")
                if isinstance(value, str):
                    ids.append(value)
        return tuple(ids)
