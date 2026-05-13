"""Markdown rendering for Hermes — session timelines and reflections."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from trustlayer.schema import AgentTraceEvent

from .reflector import Reflection, SessionSummary


def render_session_note(events: Sequence[AgentTraceEvent]) -> str:
    if not events:
        return ""
    head = events[0]
    tail = events[-1]
    front = {
        "agent_id": head.agent_id,
        "session_id": head.session_id,
        "started_at": head.timestamp.isoformat(),
        "ended_at": tail.timestamp.isoformat(),
        "event_count": len(events),
        "tags": ["memory-trace", f"agent/{head.agent_id}"],
    }
    parts: list[str] = ["---", *_yaml_lines(front), "---", ""]
    parts.append(f"# Session `{head.session_id}` — agent `{head.agent_id}`")
    parts.append("")
    parts.append("## Timeline")
    parts.append("")
    for evt in events:
        parts.append(_render_event(evt))
    return "\n".join(parts).rstrip() + "\n"


def render_reflection_note(
    reflection: Reflection, summaries: Sequence[SessionSummary]
) -> str:
    front = {
        "date": reflection.date.isoformat(),
        "sessions_summarised": len(summaries),
        "tags": ["reflection", "hermes"],
    }
    parts: list[str] = ["---", *_yaml_lines(front), "---", ""]
    parts.append(f"# Reflection — {reflection.date.isoformat()}")
    parts.append("")
    parts.append("## Headline metrics")
    for label, value in reflection.headline_metrics.items():
        parts.append(f"- **{label}:** {value}")
    parts.append("")

    if reflection.top_tools:
        parts.append("## Most-used tools")
        for tool, count in reflection.top_tools:
            parts.append(f"- `{tool}` x {count}")
        parts.append("")

    if reflection.policy_failures:
        parts.append("## Policy failures")
        for entry in reflection.policy_failures:
            parts.append(
                f"- `{entry['policy']}` on `{entry['action']}` "
                f"({entry['count']}x)"
            )
        parts.append("")

    parts.append("## Source sessions")
    for s in summaries:
        link = f"03_Memory_Traces/{_safe(s.agent_id)}/{_safe(s.session_id)}"
        parts.append(f"- [[{link}]] — {s.event_count} events")
    return "\n".join(parts).rstrip() + "\n"


def _render_event(evt: AgentTraceEvent) -> str:
    metrics = ""
    if evt.metrics.latency_ms is not None:
        metrics = f" _(latency {evt.metrics.latency_ms:.1f} ms)_"
    payload = json.dumps(evt.payload, default=str, sort_keys=True)
    return (
        f"### `{evt.event_type.value}`{metrics}\n"
        f"- timestamp: `{evt.timestamp.isoformat()}`\n"
        f"- cynefin: `{evt.cynefin_domain.value}`\n"
        f"- payload: `{payload}`\n"
    )


def _yaml_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            rendered = "[" + ", ".join(_yaml_scalar(v) for v in value) + "]"
        else:
            rendered = _yaml_scalar(value)
        lines.append(f"{key}: {rendered}")
    return lines


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, str):
        if value == "" or any(c in value for c in ":#[]{},"):
            return json.dumps(value)
        return value
    return json.dumps(value)


def _safe(value: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in value)
    return cleaned or "unknown"
