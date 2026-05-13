"""Reflection engine — turn session events into structured summaries.

The default :class:`DeterministicReflector` computes structural metrics
(tool frequency, policy failures, latency totals) without an LLM. Plug in
an LLM-backed implementation by satisfying :class:`ReflectionEngine`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date as DateType
from datetime import datetime, timezone
from typing import Any, Protocol

from trustlayer.schema import AgentTraceEvent, EventType, PolicyCheckResult


@dataclass
class SessionSummary:
    agent_id: str
    session_id: str
    event_count: int
    started_at: datetime
    ended_at: datetime
    tools_used: Counter = field(default_factory=Counter)
    policy_failures: list[dict[str, Any]] = field(default_factory=list)
    total_latency_ms: float = 0.0
    error_count: int = 0

    def compact_text(self, max_chars: int = 600) -> str:
        """Token-lean one-line summary suitable for LLM reflection prompts.

        The deterministic reflector produces a markdown note; an LLM
        reflector typically needs a much terser representation to fit
        many sessions into a single prompt.
        """
        duration_s = max((self.ended_at - self.started_at).total_seconds(), 0.0)
        parts: list[str] = [
            f"{self.agent_id}/{self.session_id}",
            f"events={self.event_count}",
            f"wall={duration_s:.1f}s",
            f"tool_latency={self.total_latency_ms:.0f}ms",
        ]
        if self.tools_used:
            top = ", ".join(f"{t}={c}" for t, c in self.tools_used.most_common(5))
            parts.append(f"tools[{top}]")
        if self.error_count:
            parts.append(f"errors={self.error_count}")
        if self.policy_failures:
            tags = ", ".join(
                f"{p.get('policy', '?')}:{p.get('action', '?')}"
                for p in self.policy_failures[:3]
            )
            extra = (
                f" +{len(self.policy_failures) - 3}"
                if len(self.policy_failures) > 3
                else ""
            )
            parts.append(f"policy_fail[{tags}{extra}]")
        out = " | ".join(parts)
        if len(out) > max_chars:
            out = out[: max_chars - 3] + "..."
        return out


@dataclass
class Reflection:
    date: DateType
    headline_metrics: dict[str, Any]
    top_tools: list[tuple[str, int]]
    policy_failures: list[dict[str, Any]]


class ReflectionEngine(Protocol):
    def summarise_session(
        self, events: Sequence[AgentTraceEvent]
    ) -> SessionSummary: ...

    def synthesise(
        self, summaries: Sequence[SessionSummary]
    ) -> Reflection: ...


class DeterministicReflector:
    """Structural reflection that needs no model inference."""

    def summarise_session(
        self, events: Sequence[AgentTraceEvent]
    ) -> SessionSummary:
        if not events:
            raise ValueError("Cannot summarise an empty session.")
        head = events[0]
        tail = events[-1]
        summary = SessionSummary(
            agent_id=head.agent_id,
            session_id=head.session_id,
            event_count=len(events),
            started_at=head.timestamp,
            ended_at=tail.timestamp,
        )
        for evt in events:
            if evt.event_type is EventType.TOOL_CALL:
                tool_name = evt.payload.get("tool_name")
                if isinstance(tool_name, str):
                    summary.tools_used[tool_name] += 1
            elif evt.event_type is EventType.TOOL_RESULT:
                if evt.payload.get("error"):
                    summary.error_count += 1
            elif evt.event_type is EventType.POLICY_CHECK:
                if evt.payload.get("result") == PolicyCheckResult.FAIL.value:
                    summary.policy_failures.append(
                        {
                            "policy": evt.payload.get("policy_name"),
                            "action": evt.payload.get("action"),
                            "reason": evt.payload.get("reason"),
                        }
                    )
            if evt.metrics.latency_ms:
                summary.total_latency_ms += evt.metrics.latency_ms
        return summary

    def synthesise(
        self, summaries: Sequence[SessionSummary]
    ) -> Reflection:
        all_tools: Counter = Counter()
        all_policy_failures: Counter = Counter()
        total_events = 0
        total_errors = 0
        total_latency = 0.0
        for s in summaries:
            all_tools.update(s.tools_used)
            for entry in s.policy_failures:
                key = (
                    str(entry.get("policy") or ""),
                    str(entry.get("action") or ""),
                )
                all_policy_failures[key] += 1
            total_events += s.event_count
            total_errors += s.error_count
            total_latency += s.total_latency_ms
        headline = {
            "sessions": len(summaries),
            "events": total_events,
            "tool_invocations": int(sum(all_tools.values())),
            "tool_errors": total_errors,
            "total_latency_ms": round(total_latency, 2),
        }
        return Reflection(
            date=datetime.now(timezone.utc).date(),
            headline_metrics=headline,
            top_tools=all_tools.most_common(10),
            policy_failures=[
                {"policy": p, "action": a, "count": c}
                for (p, a), c in all_policy_failures.most_common()
            ],
        )
