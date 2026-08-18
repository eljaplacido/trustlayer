"""The provider abstraction (ADR-020 §2).

Every backend is spoken to over its own HTTP API — no provider SDK is
vendored, which keeps `requirements-release.txt` and the `pip-audit` surface
small (ADR-020 Consequences).

Determinism: `temperature=0.0` and a seed where the backend supports one. The
prompt is hashed and recorded regardless, so a run is reproducible in
provenance even where the backend is not reproducible in output.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import httpx
from pydantic import BaseModel

from ..models import Message, ProviderResponse, Residency

DEFAULT_TIMEOUT = 120.0
"""Generous by SDK standards. A 30B model on a busy GPU can take a minute to
first token, and a timeout that fires mid-generation looks identical to a
refusal in the run record."""


class ProviderError(RuntimeError):
    """A provider could not answer. Never raised past an evaluator boundary
    without being recorded — a failed run is a run, not a silence."""


class ProviderRefusal(ProviderError):
    """The provider declined by policy rather than failing (NullProvider,
    egress refusal). Distinct because a refusal is a correct outcome."""


@runtime_checkable
class ChatProvider(Protocol):
    """What every backend must offer.

    `schema` asks the provider for structured output where the backend
    supports it; providers that cannot must still return text that the caller
    parses, so no evaluator depends on a backend-specific feature.
    """

    name: str
    residency: Residency
    model: str

    def complete(
        self,
        messages: Sequence[Message],
        *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse: ...

    def available(self) -> bool:
        """Cheap reachability probe. Used to fall back between gateways
        without making the caller wait for a full generation timeout."""
        ...


class HTTPProvider:
    """Shared HTTP plumbing. Subclasses own their wire format only.

    The `transport` seam is the whole test strategy for this package: every
    provider is exercised through `httpx.MockTransport` and no test touches
    the network (PHASE-8-DESIGN §5.3).
    """

    name = "http"
    residency = Residency.UNKNOWN

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(timeout=timeout, transport=transport, headers=headers)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HTTPProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _post(self, path: str, body: dict[str, object]) -> httpx.Response:
        try:
            response = self._client.post(f"{self.base_url}{path}", json=body)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: {exc}") from exc

    def available(self) -> bool:
        raise NotImplementedError


def schema_instruction(schema: type[BaseModel] | None) -> str:
    """Prompt-level structured-output request.

    Used for backends with no native schema parameter. Kept here rather than
    in each provider so every backend asks for the same shape, and so the
    instruction text is part of the hashed prompt.
    """
    if schema is None:
        return ""
    return (
        "\n\nRespond with a single JSON object and nothing else — no prose "
        "before or after it, no markdown fence. It must validate against this "
        f"JSON Schema:\n{schema.model_json_schema()}"
    )


def merge_system(messages: Sequence[Message]) -> tuple[str | None, list[Message]]:
    """Split a leading system message out, for APIs that take it separately."""
    system: str | None = None
    rest: list[Message] = []
    for message in messages:
        if message.role == "system" and system is None and not rest:
            system = message.content
        else:
            rest.append(message)
    return system, rest
