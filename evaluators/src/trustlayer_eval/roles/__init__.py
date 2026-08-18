"""The seven evaluator roles (ADR-020 §4, plus the operator-facing advisor)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ..models import EvaluatorRole, Finding
from .base import Evaluator, FindingList

__all__ = [
    "AdversarialVerifier",
    "CodeEmitter",
    "ControlJudge",
    "DocumentAuthor",
    "Evaluator",
    "FindingList",
    "HarnessAuditor",
    "InsightAdvisor",
    "WorkflowCritic",
    "for_role",
    "indeterminate_controls",
]


class InsightAdvisor(Evaluator):
    """Operator-facing chat over the evidence window (the dashboard Advisor)."""

    role = EvaluatorRole.INSIGHT_ADVISOR

    def build_user_turn(self, request: str) -> str:
        return (
            f"## Operator question\n\n{request}\n\n"
            f"## Evidence window ({len(self._window)} events)\n\n"
            f"{self._window.render(limit=200)}"
        )


class ControlJudge(Evaluator):
    """Judges one INDETERMINATE control. Never invoked on a decided one."""

    role = EvaluatorRole.CONTROL_JUDGE

    def __init__(self, *args: Any, control: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._control = control or {}

    def build_user_turn(self, request: str) -> str:
        return (
            f"## Control under review\n\n"
            f"{json.dumps(self._control, indent=2, sort_keys=True, default=str)}\n\n"
            f"## Question\n\n{request}\n\n"
            f"## Evidence window ({len(self._window)} events)\n\n"
            f"{self._window.render(limit=200)}"
        )


class WorkflowCritic(Evaluator):
    role = EvaluatorRole.WORKFLOW_CRITIC


class HarnessAuditor(Evaluator):
    role = EvaluatorRole.HARNESS_AUDITOR

    def __init__(self, *args: Any, config_excerpts: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._config_excerpts = config_excerpts

    def build_user_turn(self, request: str) -> str:
        return (
            f"## Task\n\n{request}\n\n"
            f"## Harness configuration\n\n{self._config_excerpts}\n\n"
            f"## Runtime evidence ({len(self._window)} events)\n\n"
            f"{self._window.render(limit=100)}"
        )


class DocumentAuthor(Evaluator):
    role = EvaluatorRole.DOCUMENT_AUTHOR


class CodeEmitter(Evaluator):
    role = EvaluatorRole.CODE_EMITTER


class AdversarialVerifier(Evaluator):
    """Refutes another role's finding (ADR-020 §4)."""

    role = EvaluatorRole.ADVERSARIAL_VERIFIER

    def __init__(self, *args: Any, target: Finding | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._target = target

    def build_user_turn(self, request: str) -> str:
        target = (
            self._target.model_dump_json(indent=2)
            if self._target is not None
            else "(none supplied)"
        )
        return (
            f"## Finding under review\n\n{target}\n\n"
            f"## Instruction\n\n{request}\n\n"
            f"## Evidence window ({len(self._window)} events)\n\n"
            f"{self._window.render(limit=200)}"
        )


_ROLES: dict[EvaluatorRole, type[Evaluator]] = {
    EvaluatorRole.INSIGHT_ADVISOR: InsightAdvisor,
    EvaluatorRole.CONTROL_JUDGE: ControlJudge,
    EvaluatorRole.WORKFLOW_CRITIC: WorkflowCritic,
    EvaluatorRole.HARNESS_AUDITOR: HarnessAuditor,
    EvaluatorRole.DOCUMENT_AUTHOR: DocumentAuthor,
    EvaluatorRole.CODE_EMITTER: CodeEmitter,
    EvaluatorRole.ADVERSARIAL_VERIFIER: AdversarialVerifier,
}


def for_role(role: EvaluatorRole) -> type[Evaluator]:
    return _ROLES[role]


def indeterminate_controls(controls: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter a scan down to the controls the control judge may see.

    Cost is bounded by construction (ADR-020 §4): the judge is invoked only on
    controls the deterministic engine could not decide. This function is the
    single place that boundary is enforced, and the test that pins the expected
    model-call count for a reference scan asserts against it — so a regression
    that fans out across every control fails CI rather than a customer's bill.
    """
    return [
        control
        for control in controls
        if str(control.get("outcome", "")).lower() == "indeterminate"
    ]
