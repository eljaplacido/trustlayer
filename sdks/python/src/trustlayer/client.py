"""HTTP client for shipping trace events to a TrustLayer collector."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from types import TracebackType
from typing import Self

import httpx

from .schema import AgentTraceEvent

logger = logging.getLogger("trustlayer")

DEFAULT_ENDPOINT = "http://localhost:8080/v1/events"
API_TOKEN_ENV_VAR = "TRUSTLAYER_API_TOKEN"


class TrustLayerClient:
    """Synchronous client that emits trace events.

    Failures are logged at WARNING and swallowed: instrumentation must never
    take down the host agent. Pass a custom ``transport`` (e.g.
    ``httpx.MockTransport``) for tests.

    The bearer token (ADR-007) resolves in this order:

    1. ``api_key`` argument (explicit wins).
    2. ``TRUSTLAYER_API_TOKEN`` environment variable.
    3. None — no Authorization header sent.
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        api_key: str | None = None,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key if api_key is not None else os.environ.get(API_TOKEN_ENV_VAR) or None
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def emit(self, event: AgentTraceEvent) -> None:
        self._send(event.model_dump_json())

    def emit_batch(self, events: Iterable[AgentTraceEvent]) -> None:
        body = "[" + ",".join(e.model_dump_json() for e in events) + "]"
        self._send(body)

    def _send(self, body: str) -> None:
        try:
            response = self._client.post(self.endpoint, content=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("trustlayer emit failed: %s", exc)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
