"""The shared `Evaluator` base (ADR-020 §4).

One retry on a grounding failure, with the rejection reason appended; a second
failure drops the finding and increments `ungrounded_rejected`. The evaluator
returns fewer findings rather than unsupported ones.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from .. import prompts, telemetry
from ..egress import EgressPolicy, EgressRefused
from ..evidence import EvidenceWindow
from ..grounding import GroundingValidator
from ..models import (
    EvaluatorRole,
    EvaluatorRun,
    Finding,
    Message,
    RedactionSummary,
    UngroundedFinding,
)
from ..providers import ChatProvider
from ..providers.base import ProviderError


class FindingList(BaseModel):
    """What every role is asked to return."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = []
    narrative: str | None = None


class Evaluator:
    """Base for the seven roles. Subclasses supply the user-turn content."""

    role: EvaluatorRole

    def __init__(
        self,
        provider: ChatProvider,
        *,
        window: EvidenceWindow,
        repo_root: Path | None = None,
        system: dict[str, Any] | None = None,
        redactions: RedactionSummary | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self._provider = provider
        self._window = window
        self._validator = GroundingValidator(window, repo_root=repo_root)
        self._egress = EgressPolicy(system)
        self._redactions = redactions or RedactionSummary()
        self._max_tokens = max_tokens

    def build_user_turn(self, request: str) -> str:
        """Role-specific user content. Subclasses override."""
        return (
            f"{request}\n\n"
            f"## Evidence window ({len(self._window)} events)\n\n"
            f"{self._window.render(limit=200)}"
        )

    def run(self, request: str) -> EvaluatorRun:
        # `load` already appends the shared grounding contract and folds it
        # into the recorded hash and version.
        prompt = prompts.load(self.role)

        decision = self._egress.decide(
            provider=self._provider.name, residency=self._provider.residency
        )

        session_id = telemetry.new_session_id()
        telemetry.emit(
            session_id,
            "AGENT_START",
            {"operation": self.role.value, "provider": self._provider.name},
        )
        telemetry.check_before_dispatch(
            session_id,
            provider=self._provider.name,
            model=self._provider.model,
            role=self.role.value,
        )

        messages = [
            Message(role="system", content=prompt.text),
            Message(role="user", content=self.build_user_turn(request)),
        ]

        started = time.monotonic()
        accepted: list[Finding] = []
        rejected: list[UngroundedFinding] = []
        narrative: str | None = None
        tokens_prompt = 0
        tokens_completion = 0
        model_name = self._provider.model

        # Two attempts total: the initial call, then one retry carrying the
        # rejection reasons. Never more — an evaluator that keeps retrying is
        # an evaluator that eventually talks its way past the validator.
        for attempt in (1, 2):
            response = self._provider.complete(
                messages, schema=FindingList, max_tokens=self._max_tokens
            )
            tokens_prompt += response.tokens_prompt
            tokens_completion += response.tokens_completion
            model_name = response.model

            parsed = _parse(response.text)
            if parsed is None:
                if attempt == 2:
                    break
                messages.append(Message(role="assistant", content=response.text))
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "That response was not a single valid JSON object matching "
                            "the schema. Return only the JSON object."
                        ),
                    )
                )
                continue

            narrative = parsed.narrative or narrative
            outcome = self._validator.validate_all(parsed.findings, attempt=attempt)
            accepted.extend(outcome.accepted)
            rejected.extend(outcome.rejected)

            if not outcome.rejected or attempt == 2:
                break

            reasons = "\n".join(f"- {r.claim!r}: {r.reason}" for r in outcome.rejected)
            messages.append(Message(role="assistant", content=response.text))
            messages.append(
                Message(
                    role="user",
                    content=(
                        "These findings were rejected as ungrounded and have been "
                        f"discarded:\n{reasons}\n\n"
                        "Return a corrected JSON object containing only findings you can "
                        "support with trace_ids from the evidence window. Do not restate "
                        "a rejected claim with a different id unless that id genuinely "
                        "supports it — returning fewer findings is correct."
                    ),
                )
            )

        duration_ms = (time.monotonic() - started) * 1000
        telemetry.emit(
            session_id,
            "LLM_CALL",
            {
                "model": model_name,
                "operation": self.role.value,
                "provider": self._provider.name,
            },
            {
                "latency_ms": duration_ms,
                "tokens_prompt": tokens_prompt,
                "tokens_completion": tokens_completion,
            },
        )
        telemetry.emit(
            session_id,
            "AGENT_END",
            {
                "status": "completed",
                "findings": len(accepted),
                "ungrounded_rejected": len(rejected),
            },
            {"latency_ms": duration_ms},
        )

        return EvaluatorRun(
            role=self.role,
            provider=self._provider.name,
            model=model_name,
            prompt_hash=prompt.sha256,
            prompt_version=prompt.version,
            evidence_window=self._window.ref(),
            duration_ms=duration_ms,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            findings=tuple(accepted),
            ungrounded_rejected=len(rejected),
            ungrounded=tuple(rejected),
            redactions=self._redactions,
            egress=decision,
            narrative=narrative,
        )


def _parse(text: str) -> FindingList | None:
    """Parse a model response into the output model, tolerating a code fence."""
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1] if len(lines) > 2 else lines[1:])
        candidate = candidate.strip()
    # Some backends prepend prose despite instructions; take the outermost
    # object rather than failing the whole run over a preamble.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return FindingList.model_validate_json(candidate[start : end + 1])
    except (ValidationError, json.JSONDecodeError):
        return None


__all__ = [
    "Evaluator",
    "EgressRefused",
    "FindingList",
    "ProviderError",
    "Sequence",
]
