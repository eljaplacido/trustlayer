"""LLM-backed reflection engine for Hermes (ADR-013).

Plugs into the :class:`ReflectionEngine` Protocol with an LLM (Ollama
by default, any OpenAI-compatible endpoint) that reads the structural
:class:`SessionSummary` outputs and produces a narrative reflection.

The LLM is **best-effort** — if the endpoint is down, times out, or
returns nonsense, the reflector falls back to the deterministic path
so Hermes never breaks because the LLM is unavailable.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from trustlayer.schema import AgentTraceEvent

from .reflector import DeterministicReflector, Reflection, ReflectionEngine, SessionSummary

logger = logging.getLogger("trustlayer.hermes.llm")

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "nemotron-3-super:120b"
DEFAULT_TIMEOUT = 30.0

_SYSTEM_PROMPT = """You are the Hermes reflection engine for TrustLayer, an agentic AI
observability platform. Your job is to produce a concise, actionable
reflection based on structural summaries of agent sessions.

Rules:
1. Write in plain English. Keep each paragraph under 3 sentences.
2. Focus on what changed: anomalies, patterns, risk signals, resource use.
3. If nothing notable happened, say so briefly. Don't invent insights.
4. The output is read by operators and other agents — be precise.
5. Output ONLY the reflection text. No preamble, no "Here is the reflection:", no markdown headers."""


@dataclass
class LLMReflection:
    """Narrative text produced by the LLM plus the structured backing data."""

    text: str
    model: str
    structured: Reflection


class LLMReflector:
    """Calls an LLM to produce narrative reflections from session summaries.

    If the LLM is unavailable or fails, falls back to the deterministic
    reflector so Hermes always produces *something* — the narrative
    reflection becomes an enrichment, not a requirement.
    """

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        fallback: ReflectionEngine | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self._client = httpx.Client(timeout=timeout, transport=transport)
        self._fallback = fallback or DeterministicReflector()
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def summarise_session(
        self, events: Sequence[AgentTraceEvent]
    ) -> SessionSummary:
        return self._fallback.summarise_session(events)

    def synthesise(
        self, summaries: Sequence[SessionSummary]
    ) -> Reflection:
        structured = self._fallback.synthesise(summaries)
        narrative = self._call_llm(summaries, structured)
        structured.headline_metrics["narrative"] = narrative
        return structured

    def reflect_narrative(
        self, summaries: Sequence[SessionSummary]
    ) -> LLMReflection:
        """Full reflection: structured stats + LLM narrative."""
        structured = self._fallback.synthesise(summaries)
        narrative = self._call_llm(summaries, structured)
        return LLMReflection(
            text=narrative,
            model=self.model,
            structured=structured,
        )

    def _call_llm(
        self,
        summaries: Sequence[SessionSummary],
        structured: Reflection,
    ) -> str:
        prompt = _build_prompt(summaries, structured)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1024},
        }
        try:
            response = self._client.post(self.endpoint, json=body)
            response.raise_for_status()
            data = response.json()
            text = _extract_ollama_content(data)
            if not text.strip():
                raise ValueError("LLM returned empty response")
            self._last_error = None
            return text.strip()
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            self._last_error = str(exc)
            logger.warning("LLM reflection failed (%s), falling back to structural summary", exc)
            return _fallback_narrative(structured)


def _build_prompt(
    summaries: Sequence[SessionSummary], structured: Reflection
) -> str:
    lines: list[str] = [
        "Below are structural summaries of agent sessions from the last reflection period.",
        "",
        "## Headline metrics",
    ]
    for label, value in structured.headline_metrics.items():
        if label == "narrative":
            continue
        lines.append(f"- **{label}:** {value}")

    if structured.top_tools:
        lines.append("")
        lines.append("## Tool usage (top 10)")
        for tool, count in structured.top_tools:
            lines.append(f"- `{tool}`: {count}x")

    if structured.policy_failures:
        lines.append("")
        lines.append("## Policy failures")
        for entry in structured.policy_failures:
            lines.append(
                f"- `{entry['policy']}` on `{entry['action']}` "
                f"({entry['count']}x)"
            )

    lines.append("")
    lines.append("## Per-session summaries")

    for i, s in enumerate(summaries, 1):
        lines.append(f"{i}. {s.compact_text()}")

    lines.append("")
    lines.append(
        "Produce a concise operator-facing reflection: what patterns do "
        "you see? Any anomalies? Risk signals? Resource concerns? "
        "Recommendations for the operator or agent developer?"
    )
    return "\n".join(lines)


def _extract_ollama_content(data: dict[str, Any]) -> str:
    content = data.get("message", {}).get("content", "")
    if isinstance(content, str):
        return content
    return str(content)


def _fallback_narrative(structured: Reflection) -> str:
    """Deterministic fallback when the LLM is unavailable."""
    metrics = structured.headline_metrics
    lines = [
        f"Auto-generated structural summary for {structured.date.isoformat()}.",
        f"",
        f"{metrics['sessions']} session(s), {metrics['events']} events, "
        f"{metrics['tool_invocations']} tool invocation(s).",
    ]
    fail_count = len(structured.policy_failures)
    if fail_count:
        lines.append(f"{fail_count} policy failure type(s) detected.")
    if metrics.get("tool_errors", 0) > 0:
        lines.append(f"{metrics['tool_errors']} tool error(s).")
    lines.append(
        "No LLM narrative available — the LLM endpoint was unreachable."
    )
    return " ".join(lines)
