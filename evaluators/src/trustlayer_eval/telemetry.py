"""Dogfooding through Guardian (ADR-020 §6).

Every evaluator call emits `AgentTraceEvent`s through the Python SDK and is
checked by `GuardianClient.check()` before dispatch. A `FAIL` verdict refuses
the call.

TrustLayer's own model use is therefore traced, policy-gated, and
integrity-chained like any other agent — which also answers Annex IV §2(a)
("third-party tools used in development") for TrustLayer itself, from the
platform's own evidence store (design principle P8).

Telemetry never takes down the caller: emission failures are logged and
swallowed, matching working agreement 2. The **policy check** is different — a
guardian that cannot be reached must not silently become a pass here, because
this is the one caller whose whole purpose is enforcing that distinction.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

log = logging.getLogger("trustlayer_eval.telemetry")

AGENT_ID = "trustlayer-evaluators"


class PolicyRefusal(RuntimeError):
    """The guardian denied the evaluator call. Not a failure — a decision."""


def enabled() -> bool:
    return os.getenv("TRUSTLAYER_ENABLED", "false").lower() in {"1", "true", "yes"}


def _base_url() -> str:
    return os.getenv("TRUSTLAYER_BASE_URL", "http://127.0.0.1:8089").rstrip("/")


@lru_cache(maxsize=1)
def _client() -> Any:
    from trustlayer import TrustLayerClient

    return TrustLayerClient(endpoint=f"{_base_url()}/v1/events")


@lru_cache(maxsize=1)
def _guardian() -> Any:
    from trustlayer import GuardianClient

    # fail_open=False: see the module docstring. An unreachable guardian is an
    # unknown verdict, and this caller may not treat unknown as PASS.
    return GuardianClient(
        endpoint=f"{_base_url()}/v1/check",
        policy_name=os.getenv("TRUSTLAYER_POLICY_NAME", "default"),
        fail_open=False,
    )


def _event(
    session_id: str, event_type: str, payload: dict[str, Any], metrics: dict[str, Any]
) -> Any:
    from trustlayer import AgentTraceEvent, CynefinDomain, EventType, Metrics

    return AgentTraceEvent(
        agent_id=AGENT_ID,
        session_id=session_id,
        event_type=EventType(event_type),
        cynefin_domain=CynefinDomain.COMPLICATED,
        payload=payload,
        metrics=Metrics(**metrics),
    )


def emit(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> UUID | None:
    """Emit one event. Returns its trace_id, or None when disabled or failed."""
    if not enabled():
        return None
    try:
        event = _event(session_id, event_type, payload, metrics or {})
        _client().emit(event)
        trace_id = getattr(event, "trace_id", None)
        return trace_id if isinstance(trace_id, UUID) else None
    except Exception as exc:  # noqa: BLE001 — instrumentation must not break the host
        log.warning("evaluator telemetry emission failed: %s", exc)
        return None


def check_before_dispatch(session_id: str, *, provider: str, model: str, role: str) -> None:
    """Policy-gate the model call. Raises `PolicyRefusal` on a FAIL verdict."""
    if not enabled():
        return
    try:
        candidate = _event(
            session_id,
            "TOOL_CALL",
            {
                "tool_name": "external_llm" if provider == "anthropic" else "local_llm",
                "tool_args": {"provider": provider, "model": model, "role": role},
            },
            {},
        )
        verdict = _guardian().check(candidate)
    except Exception as exc:  # noqa: BLE001
        # Distinguished from a FAIL: this is "we do not know", and the operator
        # is told which it was rather than being handed a silent pass.
        raise PolicyRefusal(
            f"guardian unreachable, refusing to dispatch an unchecked evaluator call: {exc}"
        ) from exc

    if str(verdict.get("decision", "")).upper() == "FAIL":
        emit(
            session_id,
            "POLICY_CHECK",
            {
                "policy_name": verdict.get("policy"),
                "action": f"dispatch {role} to {provider}",
                "result": "FAIL",
                "reason": verdict.get("reason"),
                "rule": verdict.get("rule"),
                "mode": "enforced",
            },
        )
        raise PolicyRefusal(
            f"guardian denied this evaluator call: {verdict.get('reason')} "
            f"(rule {verdict.get('rule')})"
        )


def new_session_id() -> str:
    return f"eval-{uuid4()}"
