"""Typed output models for the evaluator layer (ADR-020 §3, §7).

Everything an evaluator returns is defined here, and every model is
``extra="forbid"`` and ``frozen``. A finding that cannot be expressed in
these types cannot leave the package, which is what makes the grounding
contract enforceable rather than aspirational.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Confidence(StrEnum):
    """How strongly the evaluator holds a claim.

    Demoted — never promoted — by the grounding validator: a deterministic
    re-check that disagrees can lower this, nothing raises it.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvaluatorRole(StrEnum):
    """The six roles of ADR-020 §4."""

    CONTROL_JUDGE = "control_judge"
    WORKFLOW_CRITIC = "workflow_critic"
    HARNESS_AUDITOR = "harness_auditor"
    DOCUMENT_AUTHOR = "document_author"
    CODE_EMITTER = "code_emitter"
    ADVERSARIAL_VERIFIER = "adversarial_verifier"
    INSIGHT_ADVISOR = "insight_advisor"
    """Operator-facing chat over the evidence window (the dashboard Advisor
    pane). Shares the grounding contract with the other roles: it answers
    from cited events or it says it cannot."""


class SourceRef(BaseModel):
    """A citation into the repository rather than into the trace log."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    def resolve(self, root: Path) -> Path:
        """Absolute path under `root`, refusing to escape it.

        A citation is only checkable if it names a file inside the repository
        that was scanned; `../` in a model-produced path is a finding about the
        model, not a path to follow.
        """
        candidate = (root / self.path).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise ValueError(f"citation escapes the repository root: {self.path}")
        return candidate


class Finding(BaseModel):
    """One grounded claim (ADR-020 §3).

    ``cited_trace_ids`` has ``min_length=1`` at the type level: a finding with
    no citation is not a weak finding, it is not representable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str = Field(min_length=1)
    cited_trace_ids: tuple[UUID, ...] = Field(min_length=1)
    cited_sources: tuple[SourceRef, ...] = ()
    confidence: Confidence = Confidence.LOW
    severity: Severity = Severity.INFO
    human_review_required: bool = True
    """Defaults to True and nothing in the platform clears it automatically
    (ADR-020 Consequences). A grounded finding is one whose citations exist and
    support its shape — not one that is known to be correct."""

    remediation: str | None = None
    """What to do about it. Prose for most roles; `code_emitter` puts its
    proposed artifact here."""


class UngroundedFinding(BaseModel):
    """A finding the validator refused, kept for the run record.

    Recorded rather than discarded so "N findings suppressed as ungrounded"
    can name *what* was suppressed when a reviewer asks.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str
    reason: str
    attempt: int = Field(ge=1)


class Residency(StrEnum):
    """Where a provider's inference physically happens (ADR-020 §5)."""

    LOCAL = "local"
    EU = "eu"
    THIRD_COUNTRY = "third_country"
    UNKNOWN = "unknown"
    """Treated as THIRD_COUNTRY by the egress policy. An unlabelled endpoint
    is not a safe one."""


class EgressDecision(BaseModel):
    """Whether data was allowed to leave, and under what authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    provider: str
    residency: Residency
    data_classes: tuple[str, ...] = ()
    reason: str
    override_safeguard: str | None = None
    override_approver: str | None = None


class RedactionSummary(BaseModel):
    """What was withheld before egress — paths and counts, never values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    redacted_paths: tuple[str, ...] = ()
    redacted_count: int = Field(default=0, ge=0)
    raw_content_included: bool = False


class EvidenceWindowRef(BaseModel):
    """A re-checkable pointer at the evidence a run actually saw (ADR-020 §7).

    The result hash is what makes a past finding re-checkable against a log
    that has since grown: re-running the query and getting a different hash
    means the window moved, so the finding is not directly comparable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    result_hash: str
    event_count: int = Field(ge=0)
    first_seq: int | None = None
    last_seq: int | None = None


class HumanDecisionRef(BaseModel):
    """Link to the HUMAN_DECISION event that accepted or rejected a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: UUID
    decision: str
    decided_by: str


class EvaluatorRun(BaseModel):
    """The run record (ADR-020 §7). Art. 12 evidence about the tooling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID = Field(default_factory=uuid4)
    role: EvaluatorRole
    provider: str
    model: str
    model_version: str | None = None
    prompt_hash: str
    prompt_version: str
    evidence_window: EvidenceWindowRef
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = Field(ge=0)
    tokens_prompt: int = Field(default=0, ge=0)
    tokens_completion: int = Field(default=0, ge=0)
    cost_usd: float | None = None
    findings: tuple[Finding, ...] = ()
    ungrounded_rejected: int = Field(default=0, ge=0)
    ungrounded: tuple[UngroundedFinding, ...] = ()
    redactions: RedactionSummary = RedactionSummary()
    egress: EgressDecision
    human_decision: HumanDecisionRef | None = None
    narrative: str | None = None
    """Free prose for the operator-facing roles. Never a substitute for
    `findings` — anything asserted as fact belongs in a cited finding."""

    verifier_same_model: bool | None = None
    """True when an adversarial verification ran on the same model that
    produced the finding. Recorded rather than hidden, because same-model
    self-verification is weak (ADR-020 §4)."""

    def to_jsonl(self) -> str:
        return self.model_dump_json()


class ProviderResponse(BaseModel):
    """Parsed at the provider boundary — `dict[str, Any]` stops here (§5.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    model: str
    model_version: str | None = None
    tokens_prompt: int = Field(default=0, ge=0)
    tokens_completion: int = Field(default=0, ge=0)
    raw_finish_reason: str | None = None


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    content: str

    def as_wire(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}
