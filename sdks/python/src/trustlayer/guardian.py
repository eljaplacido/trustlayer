"""Client for the TrustLayer ``cynepic-guardian`` policy service.

The guardian is the Rust HTTP sidecar implemented in ``core-rs``. The contract:

    POST /v1/check  {"event": <AgentTraceEvent>, "policy_name": "default"}
    -> 200 {"decision": "PASS"|"FAIL"|"ESCALATE", "rule": "...", "reason": "...", "policy": "..."}

The client is **fail-open by default** so an unavailable guardian cannot
take down the host agent. Override with ``fail_open=False`` when you need
hard denial (e.g. regulated workloads where missing a policy check is
worse than blocking).
"""

from __future__ import annotations

import json
import logging
import os
from types import TracebackType
from typing import Literal, Self, TypedDict

import httpx

from .schema import AgentTraceEvent, PolicyCheckResult

logger = logging.getLogger("trustlayer.guardian")

DEFAULT_GUARDIAN_ENDPOINT = "http://127.0.0.1:8089/v1/check"
API_TOKEN_ENV_VAR = "TRUSTLAYER_API_TOKEN"


class Verdict(TypedDict):
    decision: Literal["PASS", "FAIL", "ESCALATE"]
    rule: str | None
    reason: str | None
    policy: str


class GuardianClient:
    """Synchronous client for the cynepic-guardian HTTP service.

    On transport or HTTP failure, returns a synthetic ``"policy": "fallback"``
    verdict whose ``decision`` is ``PASS`` (fail-open) or ``FAIL``
    (fail-closed) depending on ``fail_open``.

    The bearer token (ADR-007) resolves in this order:

    1. ``api_key`` argument (explicit wins).
    2. ``TRUSTLAYER_API_TOKEN`` environment variable.
    3. None — no Authorization header sent.
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_GUARDIAN_ENDPOINT,
        *,
        policy_name: str | None = None,
        api_key: str | None = None,
        timeout: float = 1.0,
        fail_open: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.policy_name = policy_name
        self.fail_open = fail_open
        resolved = api_key if api_key is not None else os.environ.get(API_TOKEN_ENV_VAR) or None
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers=self._build_headers(resolved),
        )

    @staticmethod
    def _build_headers(api_key: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def check(
        self,
        event: AgentTraceEvent,
        policy_name: str | None = None,
    ) -> Verdict:
        body = json.dumps(
            {
                "event": json.loads(event.model_dump_json()),
                "policy_name": policy_name or self.policy_name,
            }
        )
        try:
            response = self._client.post(self.endpoint, content=body)
            response.raise_for_status()
            return _coerce_verdict(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("trustlayer-guardian check failed: %s", exc)
            return self._fallback_verdict(str(exc))

    def _fallback_verdict(self, detail: str) -> Verdict:
        decision: Literal["PASS", "FAIL", "ESCALATE"] = (
            PolicyCheckResult.PASS.value if self.fail_open else PolicyCheckResult.FAIL.value
        )
        return Verdict(
            decision=decision,
            rule=None,
            reason=f"guardian unavailable: {detail}",
            policy="fallback",
        )

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


def _coerce_verdict(data: object) -> Verdict:
    if not isinstance(data, dict):
        raise ValueError(f"unexpected verdict payload type: {type(data).__name__}")
    decision = data.get("decision")
    if decision not in {"PASS", "FAIL", "ESCALATE"}:
        raise ValueError(f"unexpected verdict decision: {decision!r}")
    return Verdict(
        decision=decision,
        rule=data.get("rule"),
        reason=data.get("reason"),
        policy=str(data.get("policy", "unknown")),
    )
