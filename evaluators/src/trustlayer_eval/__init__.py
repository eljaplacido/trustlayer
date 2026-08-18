"""trustlayer-eval — pluggable evaluator providers with grounded output.

ADR-020. The deterministic evidence engine (ADR-018) decides what is decidable;
this package handles the residue that genuinely needs judgement, and holds that
judgement to a grounding contract: every finding cites events that exist in the
window it was given, or it is dropped.
"""

from __future__ import annotations

from .egress import EgressPolicy, EgressRefused
from .evidence import EvidenceWindow, window_from_events
from .grounding import GroundingError, GroundingOutcome, GroundingValidator
from .models import (
    Confidence,
    EgressDecision,
    EvaluatorRole,
    EvaluatorRun,
    EvidenceWindowRef,
    Finding,
    Message,
    ProviderResponse,
    RedactionSummary,
    Residency,
    Severity,
    SourceRef,
    UngroundedFinding,
)
from .providers import (
    AgentcenterProvider,
    AnthropicProvider,
    ChatProvider,
    NullProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderRefusal,
    from_env,
)
from .redaction import Redactor
from .roles import (
    AdversarialVerifier,
    CodeEmitter,
    ControlJudge,
    DocumentAuthor,
    Evaluator,
    HarnessAuditor,
    InsightAdvisor,
    WorkflowCritic,
    for_role,
    indeterminate_controls,
)

__version__ = "0.1.0"

__all__ = [
    "AdversarialVerifier",
    "AgentcenterProvider",
    "AnthropicProvider",
    "ChatProvider",
    "CodeEmitter",
    "Confidence",
    "ControlJudge",
    "DocumentAuthor",
    "EgressDecision",
    "EgressPolicy",
    "EgressRefused",
    "EvaluatorRole",
    "EvaluatorRun",
    "Evaluator",
    "EvidenceWindow",
    "EvidenceWindowRef",
    "Finding",
    "GroundingError",
    "GroundingOutcome",
    "GroundingValidator",
    "HarnessAuditor",
    "InsightAdvisor",
    "Message",
    "NullProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "ProviderError",
    "ProviderRefusal",
    "ProviderResponse",
    "RedactionSummary",
    "Redactor",
    "Residency",
    "Severity",
    "SourceRef",
    "UngroundedFinding",
    "WorkflowCritic",
    "for_role",
    "from_env",
    "indeterminate_controls",
    "window_from_events",
]
