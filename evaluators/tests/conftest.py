"""Shared fixtures. No test in this package touches the network."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import pytest

from trustlayer_eval.evidence import EvidenceWindow, window_from_events

#: Fixed ids so tests can assert on citation behaviour without generating any.
IN_WINDOW = UUID("11111111-1111-4111-8111-111111111111")
ALSO_IN_WINDOW = UUID("22222222-2222-4222-8222-222222222222")
#: Well-formed, and deliberately absent from every window below.
OUT_OF_WINDOW = UUID("99999999-9999-4999-8999-999999999999")


def event(trace_id: UUID, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trace_id": str(trace_id),
        "agent_id": "test-agent",
        "session_id": "test-session",
        "timestamp": "2026-08-16T09:00:00Z",
        "event_type": "TOOL_CALL",
        "cynefin_domain": "COMPLICATED",
        "payload": {"tool_name": "external_llm"},
        "metrics": {"latency_ms": 1.0},
        "seq": 1,
    }
    base.update(overrides)
    return base


@pytest.fixture
def window() -> EvidenceWindow:
    return window_from_events([event(IN_WINDOW), event(ALSO_IN_WINDOW, seq=2)], query="test-query")


def mock_provider_transport(payloads: list[str]) -> httpx.MockTransport:
    """An Ollama-shaped transport returning `payloads` in order.

    Every provider in this package is exercised through `MockTransport`
    (PHASE-8-DESIGN §5.3) — no test opens a socket.
    """
    remaining = list(payloads)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "test-model"}]})
        body = remaining.pop(0) if remaining else "{}"
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "message": {"content": body},
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 20,
            },
        )

    return httpx.MockTransport(handler)


def findings_payload(*findings: dict[str, Any], narrative: str | None = None) -> str:
    body: dict[str, Any] = {"findings": list(findings)}
    if narrative is not None:
        body["narrative"] = narrative
    return json.dumps(body)
