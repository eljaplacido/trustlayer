"""Turn compliance findings into an ordered, cited remediation plan.

A readiness score tells you *that* you are not compliant. It does not tell you
what to do on Monday. This module closes that gap: every non-passing finding is
matched against a guidance catalog and rendered as concrete work, sequenced so
the blocking items come first.

Four properties are deliberate.

**Deterministic (design principle P2).** Guidance is looked up in a catalog, not
generated. The same findings always produce the same plan, which is what makes
a plan reviewable and diffable across runs. A model may later *explain* an item
(ADR-020); it never invents one.

**Cited (P1).** Every item names the finding that triggered it and the articles
it rests on, so a reader can check the claim rather than trust it.

**Proposal-only (P4).** Nothing here writes to a repository. `artifacts` are
suggested paths for a human to review. This is an Art. 14 posture, not a
missing feature.

**Honest about its own gaps (P3, P10).** A finding with no authored guidance is
reported as `unguided`, never dropped. Silently returning a short plan would
read as "little work remains", which is the opposite of the truth.

Three dimensions of work are distinguished — technical, documentation, and
process — because the most common way a gap is closed without being closed is
fixing it in the wrong one. Writing an oversight policy does not create the
oversight process, and declaring a risk class in a document does not make the
runtime enforce it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from compliance.src.validation import load_yaml_mapping, validate_document

REMEDIATION_DIR = Path(__file__).resolve().parent.parent / "remediation"

Dimension = Literal["technical", "documentation", "process"]

#: Statuses that call for remediation. `PASS` is excluded by design: guidance
#: for something already satisfied buries the work that remains.
ACTIONABLE_STATUSES: frozenset[str] = frozenset({"FAIL", "GAP", "SKIP", "PARTIAL", "MISSING"})

#: Ordering weights. Lower sorts earlier.
_PRIORITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_EFFORT_RANK: dict[str, int] = {"S": 0, "M": 1, "L": 2}

_DEFAULT_PRIORITY = "medium"
_DEFAULT_EFFORT = "M"


@dataclass(frozen=True)
class Artifact:
    """A file the work creates or changes. A suggestion, never an action."""

    path: str
    change: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "change": self.change}


@dataclass(frozen=True)
class Guidance:
    """One entry from the catalog, as authored."""

    id: str
    title: str
    dimension: Dimension
    why: str
    steps: tuple[str, ...]
    check_ids: frozenset[str]
    control_ids: frozenset[str]
    statuses: frozenset[str]
    legal_basis: tuple[str, ...] = ()
    blocking: bool = False
    effort: str = _DEFAULT_EFFORT
    owner_role: str | None = None
    artifacts: tuple[Artifact, ...] = ()
    verification: str | None = None
    evidence_hint: str | None = None
    references: tuple[str, ...] = ()

    def matches(self, finding: Finding) -> bool:
        """Does this guidance respond to `finding`?"""
        if finding.status not in self.statuses:
            return False
        return finding.finding_id in self.check_ids or finding.finding_id in self.control_ids


@dataclass(frozen=True)
class Finding:
    """A non-passing result from any scanner, normalised.

    Both the readiness scanner (`check_id`) and the evidence linker
    (`control_id`) feed this shape, so the planner does not need to know which
    produced it.
    """

    finding_id: str
    title: str
    status: str
    details: str
    priority: str = _DEFAULT_PRIORITY
    source: str = "readiness"


@dataclass(frozen=True)
class RemediationItem:
    """One piece of work, traced to what asked for it."""

    guidance_id: str
    title: str
    dimension: Dimension
    why: str
    steps: tuple[str, ...]
    blocking: bool
    effort: str
    priority: str
    owner_role: str | None
    legal_basis: tuple[str, ...]
    artifacts: tuple[Artifact, ...]
    verification: str | None
    evidence_hint: str | None
    references: tuple[str, ...]
    #: Findings that triggered this item. More than one finding can converge on
    #: the same work; the item is emitted once and cites all of them.
    triggered_by: tuple[Finding, ...]

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """Blocking first, then priority, then cheapest — then id for stability.

        Effort ascends *within* a priority tier rather than across it: a plan
        that front-loads quick wins at the cost of leaving a blocking item open
        optimises for the appearance of progress.
        """
        return (
            0 if self.blocking else 1,
            _PRIORITY_RANK.get(self.priority, _PRIORITY_RANK[_DEFAULT_PRIORITY]),
            _EFFORT_RANK.get(self.effort, _EFFORT_RANK[_DEFAULT_EFFORT]),
            self.guidance_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "guidance_id": self.guidance_id,
            "title": self.title,
            "dimension": self.dimension,
            "why": self.why,
            "steps": list(self.steps),
            "blocking": self.blocking,
            "effort": self.effort,
            "priority": self.priority,
            "owner_role": self.owner_role,
            "legal_basis": list(self.legal_basis),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "verification": self.verification,
            "evidence_hint": self.evidence_hint,
            "references": list(self.references),
            "triggered_by": [
                {
                    "finding_id": f.finding_id,
                    "title": f.title,
                    "status": f.status,
                    "details": f.details,
                    "source": f.source,
                }
                for f in self.triggered_by
            ],
        }


@dataclass
class RemediationPlan:
    """An ordered plan, plus an explicit account of what it could not cover."""

    system_id: str
    system_name: str
    framework: str
    items: list[RemediationItem] = field(default_factory=list)
    #: Findings with no authored guidance. Surfaced, never swallowed.
    unguided: list[Finding] = field(default_factory=list)

    @property
    def blocking_items(self) -> list[RemediationItem]:
        return [i for i in self.items if i.blocking]

    def by_dimension(self, dimension: Dimension) -> list[RemediationItem]:
        return [i for i in self.items if i.dimension == dimension]

    def summary(self) -> dict[str, Any]:
        return {
            "total_items": len(self.items),
            "blocking_items": len(self.blocking_items),
            "by_dimension": {
                "technical": len(self.by_dimension("technical")),
                "documentation": len(self.by_dimension("documentation")),
                "process": len(self.by_dimension("process")),
            },
            "by_effort": {
                effort: sum(1 for i in self.items if i.effort == effort)
                for effort in ("S", "M", "L")
            },
            "unguided_findings": len(self.unguided),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_id": self.system_id,
            "system_name": self.system_name,
            "framework": self.framework,
            "summary": self.summary(),
            "items": [i.to_dict() for i in self.items],
            "unguided_findings": [
                {
                    "finding_id": f.finding_id,
                    "title": f.title,
                    "status": f.status,
                    "details": f.details,
                    "source": f.source,
                }
                for f in self.unguided
            ],
            "disclaimer": DISCLAIMER,
        }


#: Attached to every generated plan. The planner reports what the Act's text
#: requires and what TrustLayer can observe; whether a measure is sufficient
#: for a given system is a determination for the provider and their counsel.
DISCLAIMER = (
    "This plan is generated from a guidance catalog and the findings of an "
    "automated scan. It is not legal advice, and completing it does not confer "
    "conformity or a presumption of conformity. As of 2026 no harmonised "
    "standard is cited in the OJEU, so nothing does."
)


def load_catalog(path: Path) -> tuple[str, list[Guidance]]:
    """Load and validate a remediation catalog.

    Returns the framework name and its guidance entries. Raises rather than
    returning a partial catalog: guidance that silently failed to load would
    produce a plan that looks complete and is not.
    """
    document = load_yaml_mapping(path)
    validate_document(document, "remediation.schema.json")

    framework = str(document["framework"])
    entries: list[Guidance] = []
    seen: set[str] = set()

    for raw in document["guidance"]:
        guidance_id = str(raw["id"])
        if guidance_id in seen:
            raise ValueError(f"{path}: duplicate guidance id {guidance_id!r}")
        seen.add(guidance_id)

        applies = raw["applies_to"]
        statuses = applies.get("statuses")
        entries.append(
            Guidance(
                id=guidance_id,
                title=str(raw["title"]),
                dimension=raw["dimension"],
                why=str(raw["why"]),
                steps=tuple(str(s) for s in raw["steps"]),
                check_ids=frozenset(applies.get("check_ids", [])),
                control_ids=frozenset(applies.get("control_ids", [])),
                # An omitted status list means "every non-passing status" —
                # the common case, and the safe default.
                statuses=frozenset(statuses) if statuses else ACTIONABLE_STATUSES,
                legal_basis=tuple(raw.get("legal_basis", [])),
                blocking=bool(raw.get("blocking", False)),
                effort=str(raw.get("effort", _DEFAULT_EFFORT)),
                owner_role=raw.get("owner_role"),
                artifacts=tuple(
                    Artifact(path=str(a["path"]), change=str(a["change"]))
                    for a in raw.get("artifacts", [])
                ),
                verification=raw.get("verification"),
                evidence_hint=raw.get("evidence_hint"),
                references=tuple(raw.get("references", [])),
            )
        )

    return framework, entries


def default_catalog_path(framework: str) -> Path:
    """Locate the bundled catalog for a framework."""
    return REMEDIATION_DIR / f"{framework}.yaml"


def findings_from_readiness(report: dict[str, Any]) -> list[Finding]:
    """Extract actionable findings from a readiness report."""
    findings: list[Finding] = []
    for check in report.get("checks", []):
        status = str(check.get("status", ""))
        if status not in ACTIONABLE_STATUSES:
            continue
        findings.append(
            Finding(
                finding_id=str(check.get("check_id", "")),
                title=str(check.get("check_title", "")),
                status=status,
                details=str(check.get("details", "")),
                priority=str(check.get("priority", _DEFAULT_PRIORITY)),
                source="readiness",
            )
        )
    return findings


def findings_from_evidence(report: dict[str, Any]) -> list[Finding]:
    """Extract actionable findings from an evidence-linker compliance report.

    A control with no supporting evidence is a `MISSING` finding. This is where
    the plan stops being about paperwork: it reports controls the *runtime*
    could not substantiate.
    """
    findings: list[Finding] = []
    for control in report.get("controls", []):
        satisfied = control.get("satisfied")
        if satisfied is True:
            continue
        findings.append(
            Finding(
                finding_id=str(control.get("control_id", "")),
                title=str(control.get("control_title", "")),
                status="PARTIAL" if control.get("evidence_count") else "MISSING",
                details=str(
                    control.get("details")
                    or f"{control.get('evidence_count', 0)} matching events found"
                ),
                priority=str(control.get("priority", _DEFAULT_PRIORITY)),
                source="evidence",
            )
        )
    return findings


class RemediationPlanner:
    """Match findings against a guidance catalog and order the result."""

    def __init__(self, guidance: Sequence[Guidance], framework: str) -> None:
        self._guidance = list(guidance)
        self._framework = framework

    @classmethod
    def from_catalog(cls, path: Path) -> RemediationPlanner:
        framework, guidance = load_catalog(path)
        return cls(guidance, framework)

    def plan(
        self,
        findings: Iterable[Finding],
        *,
        system_id: str = "unknown",
        system_name: str = "Unknown System",
    ) -> RemediationPlan:
        """Build a plan from findings.

        Several findings can converge on one piece of work — instrumentation
        being absent makes every evidence-backed control unsatisfiable — so
        items are keyed by guidance id and cite every finding that triggered
        them. Emitting the same work once per finding would make a
        single-cause plan look like twenty problems.
        """
        collected: dict[str, list[Finding]] = {}
        unguided: list[Finding] = []

        for finding in findings:
            matched = [g for g in self._guidance if g.matches(finding)]
            if not matched:
                unguided.append(finding)
                continue
            for guidance in matched:
                collected.setdefault(guidance.id, []).append(finding)

        by_id = {g.id: g for g in self._guidance}
        items: list[RemediationItem] = []
        for guidance_id, triggers in collected.items():
            guidance = by_id[guidance_id]
            items.append(
                RemediationItem(
                    guidance_id=guidance.id,
                    title=guidance.title,
                    dimension=guidance.dimension,
                    why=guidance.why,
                    steps=guidance.steps,
                    blocking=guidance.blocking,
                    effort=guidance.effort,
                    # The most severe triggering finding sets the item's
                    # priority. Taking the mildest would let one low-priority
                    # match mask a critical one.
                    priority=_most_severe([t.priority for t in triggers]),
                    owner_role=guidance.owner_role,
                    legal_basis=guidance.legal_basis,
                    artifacts=guidance.artifacts,
                    verification=guidance.verification,
                    evidence_hint=guidance.evidence_hint,
                    references=guidance.references,
                    triggered_by=tuple(triggers),
                )
            )

        items.sort(key=lambda i: i.sort_key)
        # Deterministic ordering for the honest-gap list too, so a plan
        # regenerated from identical input is byte-identical.
        unguided.sort(key=lambda f: (f.finding_id, f.source))

        return RemediationPlan(
            system_id=system_id,
            system_name=system_name,
            framework=self._framework,
            items=items,
            unguided=unguided,
        )


def _most_severe(priorities: Sequence[str]) -> str:
    """The highest-severity priority in the list."""
    return min(
        priorities,
        key=lambda p: _PRIORITY_RANK.get(p, _PRIORITY_RANK[_DEFAULT_PRIORITY]),
        default=_DEFAULT_PRIORITY,
    )


#: Section headings and their framing, in the order a reader should work
#: through them. Technical comes first because until instrumentation exists,
#: controls that depend on runtime evidence cannot be substantiated at all.
_DIMENSION_SECTIONS: tuple[tuple[Dimension, str, str], ...] = (
    (
        "technical",
        "Technical",
        (
            "Code, configuration and instrumentation. Until these land, "
            "controls that depend on runtime evidence cannot be substantiated "
            "at all."
        ),
    ),
    (
        "documentation",
        "Documentation",
        (
            "Artifacts an assessor or a deployer reads. Each should cite "
            "something dated rather than assert itself."
        ),
    ),
    (
        "process",
        "Process",
        (
            "Recurring human activity with a named owner and a cadence. A "
            "process documented but never run is evidence that it lapsed, "
            "which is worse than not claiming it."
        ),
    ),
)


def render_markdown(plan: RemediationPlan) -> str:
    """Render a plan as review-ready Markdown.

    Grouped by dimension after the blocking section, because the three
    dimensions are usually different people's work — a plan interleaving them
    reads as one impossible task instead of three tractable ones.
    """
    lines: list[str] = [
        f"# Remediation plan — {plan.system_name}",
        "",
        f"**System:** `{plan.system_id}`  ",
        f"**Framework:** `{plan.framework}`",
        "",
        "> " + DISCLAIMER.replace("\n", " "),
        "",
        "## Summary",
        "",
    ]

    summary = plan.summary()
    lines += [
        "| | Count |",
        "|---|---|",
        f"| Actions | {summary['total_items']} |",
        f"| Blocking a conformity claim | {summary['blocking_items']} |",
        f"| Technical | {summary['by_dimension']['technical']} |",
        f"| Documentation | {summary['by_dimension']['documentation']} |",
        f"| Process | {summary['by_dimension']['process']} |",
        f"| Findings with no guidance | {summary['unguided_findings']} |",
        "",
    ]

    if not plan.items and not plan.unguided:
        lines += [
            "No actionable findings. Note that this reflects the checks that ran,",
            "not the obligations that apply — a clean plan is not a conformity claim.",
            "",
        ]
        return "\n".join(lines)

    blocking = plan.blocking_items
    if blocking:
        lines += [
            "## Blocking first",
            "",
            "These gaps block a conformity claim outright rather than weakening",
            "it. Nothing below is worth starting until these are underway.",
            "",
        ]
        lines += [
            f"1. **{item.title}** — `{item.guidance_id}` ({item.effort})" for item in blocking
        ]
        lines.append("")

    for dimension, heading, blurb in _DIMENSION_SECTIONS:
        items = plan.by_dimension(dimension)
        if not items:
            continue
        lines += [f"## {heading}", "", blurb, ""]
        for item in items:
            lines += _render_item(item)

    if plan.unguided:
        lines += [
            "## Findings with no authored guidance",
            "",
            "These were flagged by a scan but the catalog has nothing to say",
            "about them. Listed rather than dropped: a shorter plan is not a",
            "smaller problem. Add guidance to",
            f"`compliance/remediation/{plan.framework}.yaml` to close the gap.",
            "",
            "| Finding | Status | Source | Detail |",
            "|---|---|---|---|",
        ]
        for finding in plan.unguided:
            detail = finding.details.replace("|", "\\|")
            lines.append(
                f"| `{finding.finding_id}` | {finding.status} | {finding.source} | {detail} |"
            )
        lines.append("")

    return "\n".join(lines)


def _render_item(item: RemediationItem) -> list[str]:
    """One remediation item as Markdown."""
    badges = [item.effort]
    if item.blocking:
        badges.append("blocking")
    if item.owner_role:
        badges.append(item.owner_role)

    lines = [
        f"### {item.title}",
        "",
        f"`{item.guidance_id}` · {' · '.join(badges)} · priority {item.priority}",
        "",
    ]
    if item.legal_basis:
        lines += [f"**Basis:** {', '.join(item.legal_basis)}", ""]

    lines += ["**Why this matters**", "", item.why.strip(), "", "**Steps**", ""]
    lines += [f"{n}. {step}" for n, step in enumerate(item.steps, start=1)]
    lines.append("")

    if item.artifacts:
        lines += ["**Suggested artifacts** (proposals — nothing is written for you)", ""]
        lines += [f"- `{a.path}` — {a.change}" for a in item.artifacts]
        lines.append("")

    if item.verification:
        lines += ["**How to verify it is done**", "", item.verification.strip(), ""]

    if item.evidence_hint:
        lines += ["**Runtime evidence**", "", item.evidence_hint.strip(), ""]

    triggers = ", ".join(f"`{t.finding_id}` ({t.status})" for t in item.triggered_by)
    lines += [f"**Triggered by:** {triggers}", ""]

    if item.references:
        lines += ["**References:** " + ", ".join(item.references), ""]

    return lines


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m compliance.src.remediation",
        description=(
            "Turn compliance findings into an ordered remediation plan. "
            "Reads a readiness report and/or an evidence report; writes a plan. "
            "Never modifies the project."
        ),
    )
    parser.add_argument(
        "--readiness",
        type=Path,
        help="Path to a readiness report JSON (from readiness_scanner --output).",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        help="Path to a compliance report JSON (from evidence_linker).",
    )
    parser.add_argument(
        "--framework",
        default="eu-ai-act-v1",
        help="Guidance catalog to use (default: eu-ai-act-v1).",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        help="Explicit catalog path, overriding --framework.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write here instead of stdout.",
    )
    parser.add_argument(
        "--fail-on-blocking",
        action="store_true",
        help="Exit 1 when the plan contains blocking items, for CI gating.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.readiness and not args.evidence:
        parser.error("supply --readiness and/or --evidence")

    catalog_path = args.catalog or default_catalog_path(args.framework)
    if not catalog_path.exists():
        print(f"error: no guidance catalog at {catalog_path}", file=sys.stderr)
        return 2

    planner = RemediationPlanner.from_catalog(catalog_path)

    findings: list[Finding] = []
    system_id = "unknown"
    system_name = "Unknown System"

    if args.readiness:
        report = json.loads(args.readiness.read_text(encoding="utf-8"))
        findings += findings_from_readiness(report)
        system_id = report.get("system_id", system_id)
        system_name = report.get("system_name", system_name)

    if args.evidence:
        report = json.loads(args.evidence.read_text(encoding="utf-8"))
        findings += findings_from_evidence(report)
        # Only fill identity from the evidence report if readiness did not
        # supply it; readiness is the authority on system identity.
        if system_id == "unknown":
            system_id = report.get("system_id", system_id)
            system_name = report.get("system_name", system_name)

    plan = planner.plan(findings, system_id=system_id, system_name=system_name)

    rendered = (
        json.dumps(plan.to_dict(), indent=2) if args.format == "json" else render_markdown(plan)
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(rendered)

    if args.fail_on_blocking and plan.blocking_items:
        print(
            f"{len(plan.blocking_items)} blocking item(s) remain",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
