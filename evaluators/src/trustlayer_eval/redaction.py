"""Redaction before egress (ADR-020 §5).

Default projection is the envelope plus an allowlisted payload subset. Raw
`prompt` / `response` bodies are **opt-in, not opt-out** — the same stance the
SDK bridges take with `TRUSTLAYER_CAPTURE_CONTENT`.

What was redacted is recorded — field paths and a count, never values — so a
reviewer can tell whether a finding was made on partial information.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .models import RedactionSummary

#: Envelope fields always kept: they carry no content, and without them a
#: finding cannot cite anything.
ENVELOPE_FIELDS = (
    "trace_id",
    "agent_id",
    "session_id",
    "timestamp",
    "event_type",
    "parent_trace_id",
    "cynefin_domain",
    "seq",
)

#: Payload keys that describe *what happened* rather than *what was said*.
DEFAULT_PAYLOAD_ALLOWLIST = frozenset(
    {
        "tool_name",
        "operation",
        "model",
        "policy_name",
        "action",
        "result",
        "reason",
        "rule",
        "mode",
        "status",
        "error_type",
        "stage",
        "decision",
        "confidence",
    }
)

#: Keys whose values are content by definition. Included only when the caller
#: opts in, and named here so the opt-in is a single explicit list.
CONTENT_KEYS = frozenset({"prompt", "completion", "response", "input_summary", "output_summary"})


class Redactor:
    """Projects events down to what an evaluator is allowed to see."""

    def __init__(
        self,
        *,
        payload_allowlist: Iterable[str] | None = None,
        include_raw_content: bool = False,
    ) -> None:
        self._allowlist = frozenset(payload_allowlist or DEFAULT_PAYLOAD_ALLOWLIST)
        self._include_raw_content = include_raw_content
        self._redacted_paths: set[str] = set()
        self._redacted_count = 0

    def redact_event(self, event: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for field in ENVELOPE_FIELDS:
            if field in event:
                out[field] = event[field]

        payload = event.get("payload")
        if isinstance(payload, dict):
            kept: dict[str, Any] = {}
            for key, value in payload.items():
                if key in self._allowlist:
                    kept[key] = value
                elif key in CONTENT_KEYS and self._include_raw_content:
                    kept[key] = value
                else:
                    self._redacted_paths.add(f"payload.{key}")
                    self._redacted_count += 1
            out["payload"] = kept

        metrics = event.get("metrics")
        if isinstance(metrics, dict):
            # Metrics are numbers about execution, not content — kept whole.
            out["metrics"] = metrics
        return out

    def redact_all(self, events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.redact_event(event) for event in events]

    def summary(self) -> RedactionSummary:
        return RedactionSummary(
            redacted_paths=tuple(sorted(self._redacted_paths)),
            redacted_count=self._redacted_count,
            raw_content_included=self._include_raw_content,
        )
