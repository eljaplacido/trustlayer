"""The grounding validator (ADR-020 §3) — the core of the package.

A compliance artifact containing one fabricated citation is worse than no
artifact: an auditor who finds it discards everything else the platform
produced, including the deterministic parts that were correct. So a finding
that cannot be grounded is **rejected, not repaired**, and the evaluator
returns fewer findings rather than unsupported ones.

There is no configuration that disables this.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .evidence import EvidenceWindow
from .models import Confidence, Finding, UngroundedFinding


class GroundingError(ValueError):
    """A finding failed validation. Carries the reason for the retry prompt."""


@dataclass(frozen=True)
class GroundingOutcome:
    """What survived validation, and what did not."""

    accepted: tuple[Finding, ...]
    rejected: tuple[UngroundedFinding, ...]

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


class GroundingValidator:
    """Checks every finding against the window before it leaves the package."""

    def __init__(
        self,
        window: EvidenceWindow,
        *,
        repo_root: Path | None = None,
    ) -> None:
        self._window = window
        self._repo_root = repo_root

    def check(self, finding: Finding) -> Finding:
        """Return the finding, possibly demoted. Raise if it cannot be grounded."""
        self._check_citations_exist(finding)
        self._check_no_duplicate_citations(finding)
        checked = self._check_sources_resolve(finding)
        return checked

    def validate_all(self, findings: Sequence[Finding], *, attempt: int = 1) -> GroundingOutcome:
        accepted: list[Finding] = []
        rejected: list[UngroundedFinding] = []
        for finding in findings:
            try:
                accepted.append(self.check(finding))
            except GroundingError as exc:
                rejected.append(
                    UngroundedFinding(claim=finding.claim, reason=str(exc), attempt=attempt)
                )
        return GroundingOutcome(accepted=tuple(accepted), rejected=tuple(rejected))

    # -- individual rules -------------------------------------------------

    def _check_citations_exist(self, finding: Finding) -> None:
        """Rule 1: every cited id must exist in the supplied window.

        Ids outside the window, or invented, fail. This is the rule that
        catches the failure mode the ADR exists to prevent: a plausible,
        well-formed UUID that names nothing.
        """
        unknown = [tid for tid in finding.cited_trace_ids if tid not in self._window]
        if unknown:
            listed = ", ".join(str(t) for t in unknown)
            raise GroundingError(
                f"cited trace_ids not present in the evidence window: {listed}. "
                "Cite only ids that appear in the events you were given."
            )

    def _check_no_duplicate_citations(self, finding: Finding) -> None:
        """Duplicated ids inflate apparent support without adding any."""
        seen: set[str] = set()
        duplicates: set[str] = set()
        for tid in finding.cited_trace_ids:
            key = str(tid)
            if key in seen:
                duplicates.add(key)
            seen.add(key)
        if duplicates:
            raise GroundingError(
                f"duplicate trace_ids in citations: {', '.join(sorted(duplicates))}. "
                "Each cited id must appear once."
            )

    def _check_sources_resolve(self, finding: Finding) -> Finding:
        """Rule 2: every cited source path must resolve, and the lines exist.

        Skipped when no repository root was supplied — a source citation that
        cannot be checked is demoted rather than accepted at face value, so an
        unconfigured caller loses confidence, not correctness.
        """
        if not finding.cited_sources:
            return finding

        if self._repo_root is None:
            return _demote(
                finding,
                Confidence.LOW,
            )

        for source in finding.cited_sources:
            if source.end_line < source.start_line:
                raise GroundingError(
                    f"{source.path}: end_line {source.end_line} precedes "
                    f"start_line {source.start_line}"
                )
            try:
                resolved = source.resolve(self._repo_root)
            except ValueError as exc:
                raise GroundingError(str(exc)) from exc
            if not resolved.is_file():
                raise GroundingError(f"cited source does not exist: {source.path}")
            try:
                line_count = sum(1 for _ in resolved.open("r", encoding="utf-8", errors="replace"))
            except OSError as exc:
                raise GroundingError(f"cited source unreadable: {source.path}: {exc}") from exc
            if source.start_line > line_count:
                raise GroundingError(
                    f"{source.path} has {line_count} lines; "
                    f"cited range starts at {source.start_line}"
                )
        return finding


def _demote(finding: Finding, ceiling: Confidence) -> Finding:
    """Lower a finding's confidence to at most `ceiling`. Never raises it."""
    order = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
    if order[finding.confidence] <= order[ceiling]:
        return finding
    return finding.model_copy(update={"confidence": ceiling})
