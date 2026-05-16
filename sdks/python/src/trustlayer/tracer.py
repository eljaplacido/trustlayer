"""High-level tracer that ties events to an agent + session."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from .client import TrustLayerClient
from .guardian import GuardianClient, Verdict
from .schema import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
    Metrics,
    PolicyCheckPayload,
    PolicyCheckResult,
    ToolCallPayload,
    ToolResultPayload,
)


class Tracer:
    """Bind an ``agent_id``/``session_id`` and emit typed trace events.

    Most callers will use :meth:`tool_call` as a context manager:

        tracer = Tracer(agent_id="researcher")
        with tracer.tool_call("web.search", {"q": "trustlayer"}) as out:
            out["value"] = run_search(...)
    """

    def __init__(
        self,
        agent_id: str,
        session_id: str | None = None,
        client: TrustLayerClient | None = None,
        cynefin_domain: CynefinDomain = CynefinDomain.DISORDER,
    ) -> None:
        self.agent_id = agent_id
        self.session_id = session_id or str(uuid4())
        self.client = client or TrustLayerClient()
        self.cynefin_domain = cynefin_domain

    def emit(
        self,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        metrics: Metrics | None = None,
        cynefin_domain: CynefinDomain | None = None,
    ) -> AgentTraceEvent:
        event = AgentTraceEvent(
            agent_id=self.agent_id,
            session_id=self.session_id,
            event_type=event_type,
            cynefin_domain=cynefin_domain or self.cynefin_domain,
            payload=payload or {},
            metrics=metrics or Metrics(),
        )
        self.client.emit(event)
        return event

    @contextmanager
    def tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Emit ``TOOL_CALL`` then ``TOOL_RESULT`` around a block.

        Set ``out["value"]`` inside the block to attach the tool's return
        value to the result event.
        """
        self.emit(
            EventType.TOOL_CALL,
            payload=ToolCallPayload(
                tool_name=tool_name, tool_args=tool_args or {}
            ).model_dump(),
        )
        start = time.perf_counter()
        out: dict[str, Any] = {}
        try:
            yield out
        except Exception as exc:
            self.emit(
                EventType.TOOL_RESULT,
                payload=ToolResultPayload(
                    tool_name=tool_name, error=repr(exc)
                ).model_dump(),
                metrics=Metrics(latency_ms=(time.perf_counter() - start) * 1000),
            )
            raise
        self.emit(
            EventType.TOOL_RESULT,
            payload=ToolResultPayload(
                tool_name=tool_name, result=out.get("value")
            ).model_dump(),
            metrics=Metrics(latency_ms=(time.perf_counter() - start) * 1000),
        )

    def policy_check(
        self,
        policy_name: str,
        action: str,
        result: PolicyCheckResult,
        reason: str | None = None,
    ) -> AgentTraceEvent:
        return self.emit(
            EventType.POLICY_CHECK,
            payload=PolicyCheckPayload(
                policy_name=policy_name,
                action=action,
                result=result,
                reason=reason,
            ).model_dump(),
        )

    def check(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        *,
        guardian: GuardianClient,
        policy_name: str | None = None,
        cynefin_domain: CynefinDomain | None = None,
    ) -> Verdict:
        """Ask the guardian to adjudicate a candidate ``TOOL_CALL`` and record the verdict.

        Emits a ``TOOL_CALL`` event, forwards it to the guardian, and emits a
        follow-up ``POLICY_CHECK`` carrying the verdict. The caller inspects
        the returned :class:`Verdict` and decides whether to actually invoke
        the tool (typically: only on ``PASS``).

        The event sent to the guardian is the same one that was emitted,
        so the trace and the policy decision are correlated by ``trace_id``.
        """
        candidate = self.emit(
            EventType.TOOL_CALL,
            payload=ToolCallPayload(
                tool_name=tool_name, tool_args=tool_args or {}
            ).model_dump(),
            cynefin_domain=cynefin_domain,
        )
        verdict = guardian.check(candidate, policy_name=policy_name)
        self.policy_check(
            policy_name=verdict["policy"],
            action=f"invoke {tool_name}",
            result=PolicyCheckResult(verdict["decision"]),
            reason=verdict["reason"],
        )
        return verdict
