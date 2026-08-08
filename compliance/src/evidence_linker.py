"""
Evidence Linker - Links TrustLayer trace events to compliance controls.

Queries the TrustLayer trace store and evaluates control evidence queries
against what the system actually did.

Phase 8 (ADR-018) changed what this module reports. It used to answer
`satisfied: bool` from a presence check, which conflated "we wrote it down"
with "the runtime proves it" — gap G4, and the reason two dogfooded projects
both scored 100%. It now reports an **assurance tier** per control and never
blends the tiers into one number.

Report JSON carries `schema_version: 2`. Consumers branch on it; `satisfied` is
gone rather than deprecated, because a boolean that quietly meant "declared" is
worse than one that is absent.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from compliance.src.evidence_query import (
    AssuranceReport,
    AssuranceTier,
    Determination,
    EvidenceQuery,
    IntegrityStatus,
    QueryOutcome,
    QueryResult,
    Violation,
    assign_tier,
    tier_at_least,
)
from compliance.src.validation import load_yaml_mapping, validate_document

#: Report schema version. Bumped when the control record's shape changes.
SCHEMA_VERSION = 2


@dataclass
class ControlEvidence:
    """What the runtime could establish about one control."""

    control_id: str
    control_title: str
    assurance: AssuranceTier
    outcome: QueryOutcome
    population: int
    satisfied_count: int
    coverage_ratio: float | None = None
    violations: tuple[Violation, ...] = ()
    determination: Determination = Determination.DETERMINISTIC
    integrity: IntegrityStatus = IntegrityStatus.NOT_CHECKED
    evidence_samples: list[dict[str, Any]] = field(default_factory=list)
    gap_reason: str | None = None
    #: Set when the control is not yet in force. Reported separately rather
    #: than as a failure — scoring a system against an obligation that does not
    #: apply yet produces noise that hides the obligations that do.
    applies_from: str | None = None
    not_yet_applicable: bool = False
    #: Set when the control does not address this system's provider role (G9).
    not_applicable_to_role: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "control_title": self.control_title,
            "assurance": str(self.assurance),
            "outcome": str(self.outcome),
            "population": self.population,
            "satisfied_count": self.satisfied_count,
            "coverage_ratio": self.coverage_ratio,
            "violations": [v.to_dict() for v in self.violations],
            "determination": str(self.determination),
            "integrity": str(self.integrity),
            "evidence_samples": self.evidence_samples[:5],
            "gap_reason": self.gap_reason,
            "applies_from": self.applies_from,
            "not_yet_applicable": self.not_yet_applicable,
            "not_applicable_to_role": self.not_applicable_to_role,
        }


@dataclass
class ComplianceReport:
    """Compliance report for an AI system."""

    system_id: str
    system_name: str
    framework: str
    controls: list[ControlEvidence]
    summary: dict[str, Any] = field(default_factory=dict)

    def assurance(self) -> AssuranceReport:
        """Per-tier counts over the controls that actually apply."""
        report = AssuranceReport()
        for control in self.controls:
            if control.not_yet_applicable or control.not_applicable_to_role:
                continue
            report.add(control.assurance)
            if control.outcome is QueryOutcome.INDETERMINATE:
                report.indeterminate += 1
        return report

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "schema_version": SCHEMA_VERSION,
            "system_id": self.system_id,
            "system_name": self.system_name,
            "framework": self.framework,
            "controls": [c.to_dict() for c in self.controls],
            "assurance": self.assurance().to_dict(),
            "summary": self.summary,
        }


class EvidenceLinker:
    """Links trace events to compliance controls."""

    def __init__(
        self,
        trace_store_url: str = "http://127.0.0.1:8089",
        api_token: str | None = None,
    ) -> None:
        """Initialize evidence linker.

        Args:
            trace_store_url: URL of TrustLayer trace store
            api_token: Optional API token for authentication
        """
        self.trace_store_url = trace_store_url.rstrip("/")
        self.api_token = api_token

    def load_control_framework(self, framework_path: Path) -> dict[str, Any]:
        """Load control framework from YAML file.

        Args:
            framework_path: Path to control framework YAML file

        Returns:
            Control framework dictionary
        """
        framework = load_yaml_mapping(framework_path)
        validate_document(framework, "control.schema.json")
        return framework

    def load_system_registry(self, system_path: Path) -> dict[str, Any]:
        """Load system registry from YAML file.

        Args:
            system_path: Path to system registry YAML file

        Returns:
            System registry dictionary
        """
        registry = load_yaml_mapping(system_path)
        validate_document(registry, "system.schema.json")
        return registry

    def query_trace_store(
        self,
        agent_id: str | None = None,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query TrustLayer trace store for events.

        Args:
            agent_id: Filter by agent ID
            session_id: Filter by session ID
            event_type: Filter by event type
            limit: Maximum number of events to return

        Returns:
            List of trace events
        """
        params: dict[str, Any] = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        if session_id:
            params["session_id"] = session_id
        if event_type:
            params["event_type"] = event_type

        headers = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        try:
            response = httpx.get(
                f"{self.trace_store_url}/v1/events",
                params=params,
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            events = response.json()
            if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
                raise ValueError("Trace store returned an invalid events response")
            return events
        except (httpx.HTTPError, ValueError) as e:
            print(f"Warning: Could not query trace store: {e}")
            return []

    def check_integrity(self, agent_id: str | None) -> IntegrityStatus:
        """Ask the store whether this agent's evidence chain verifies (ADR-017).

        A backend with no chain answers `501`, which maps to `UNCHAINED` — an
        honest "we cannot attest", distinct from `FAILED`, which means a chain
        exists and is broken. Conflating them would let an unchained store look
        the same as a tampered one, in either direction.
        """
        if not agent_id:
            return IntegrityStatus.NOT_CHECKED

        headers = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        try:
            response = httpx.get(
                f"{self.trace_store_url}/v1/integrity/verify",
                params={"agent_id": agent_id},
                headers=headers,
                timeout=10.0,
            )
            if response.status_code == 501:
                return IntegrityStatus.UNCHAINED
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                return IntegrityStatus.NOT_CHECKED
            chains = body.get("chains") or []
            if not chains:
                # The store keeps chains but has none for this agent — nothing
                # to verify is not the same as verified.
                return IntegrityStatus.UNCHAINED
            return IntegrityStatus.VERIFIED if body.get("ok") else IntegrityStatus.FAILED
        except (httpx.HTTPError, ValueError):
            # Never guess VERIFIED. An unreachable store must not be able to
            # raise a control's assurance.
            return IntegrityStatus.NOT_CHECKED

    @staticmethod
    def control_applies(
        control: dict[str, Any],
        *,
        provider_role: str | None,
        risk_class: str | None,
        today: date | None = None,
    ) -> tuple[bool, bool]:
        """Does this control apply to this system, and is it in force yet?

        Returns `(applies_to_role, in_force)`. Both are reported rather than
        used to silently drop the control: a deployer scored against provider
        obligations is gap G9, and an obligation that has not commenced is
        information the operator wants ("applies in four months"), not a
        failure to fix today.
        """
        roles = control.get("applies_to_roles")
        applies_to_role = True
        if roles and provider_role:
            applies_to_role = provider_role in roles

        classes = control.get("risk_classes")
        if classes and risk_class and risk_class not in classes:
            applies_to_role = False

        in_force = True
        applies_from = control.get("applies_from")
        if applies_from:
            # UTC rather than local time: a commencement date is a legal
            # fact, and a scan run in two time zones must not disagree
            # about whether an obligation is in force.
            reference = today or datetime.now(tz=UTC).date()
            try:
                commencement = date.fromisoformat(str(applies_from))
            except ValueError:
                # A malformed date must not silently exempt a control.
                commencement = date.min
            in_force = reference >= commencement

        return applies_to_role, in_force

    def match_events_to_control(
        self,
        events: list[dict[str, Any]],
        control: dict[str, Any],
        *,
        provider_role: str | None = None,
        risk_class: str | None = None,
        integrity: IntegrityStatus = IntegrityStatus.NOT_CHECKED,
        declared: bool = False,
        today: date | None = None,
    ) -> ControlEvidence:
        """Evaluate one control's evidence query and assign an assurance tier."""
        control_id = control["id"]
        control_title = control["title"]
        applies_from = control.get("applies_from")

        applies_to_role, in_force = self.control_applies(
            control, provider_role=provider_role, risk_class=risk_class, today=today
        )

        if not applies_to_role or not in_force:
            reason = (
                f"does not apply to provider_role {provider_role!r}"
                if not applies_to_role
                else f"not in force until {applies_from}"
            )
            return ControlEvidence(
                control_id=control_id,
                control_title=control_title,
                assurance=AssuranceTier.UNKNOWN,
                outcome=QueryOutcome.INDETERMINATE,
                population=0,
                satisfied_count=0,
                gap_reason=reason,
                applies_from=str(applies_from) if applies_from else None,
                not_yet_applicable=not in_force,
                not_applicable_to_role=not applies_to_role,
                integrity=integrity,
            )

        evidence_query = control.get("evidence_query")
        if not evidence_query:
            # No query means the runtime was never asked. That is DECLARED at
            # best — a control can still be asserted in documentation — and
            # never a failure of the system under assessment.
            return ControlEvidence(
                control_id=control_id,
                control_title=control_title,
                assurance=AssuranceTier.DECLARED if declared else AssuranceTier.UNKNOWN,
                outcome=QueryOutcome.INDETERMINATE,
                population=0,
                satisfied_count=0,
                gap_reason="No evidence query defined, so the runtime was never asked",
                integrity=integrity,
                applies_from=str(applies_from) if applies_from else None,
            )

        query = EvidenceQuery.parse(evidence_query)
        problems = query.validate()
        if problems:
            # A malformed query must not read as a satisfied control.
            return ControlEvidence(
                control_id=control_id,
                control_title=control_title,
                assurance=AssuranceTier.UNKNOWN,
                outcome=QueryOutcome.INDETERMINATE,
                population=0,
                satisfied_count=0,
                gap_reason="; ".join(problems),
                integrity=integrity,
                applies_from=str(applies_from) if applies_from else None,
            )

        result: QueryResult = query.evaluate(events)
        tier = assign_tier(result, declared=declared, integrity=integrity)

        matching = [
            e for e in events if not query.event_types or e.get("event_type") in query.event_types
        ]

        return ControlEvidence(
            control_id=control_id,
            control_title=control_title,
            assurance=tier,
            outcome=result.outcome,
            population=result.population,
            satisfied_count=result.satisfied_count,
            coverage_ratio=result.coverage_ratio,
            violations=result.violations,
            integrity=integrity,
            evidence_samples=matching[:10],
            gap_reason=result.reason,
            applies_from=str(applies_from) if applies_from else None,
        )

    def generate_compliance_report(
        self,
        system_path: Path,
        framework_path: Path,
    ) -> ComplianceReport:
        """Generate compliance report for an AI system.

        Args:
            system_path: Path to system registry YAML
            framework_path: Path to control framework YAML

        Returns:
            ComplianceReport with control satisfaction status
        """
        system_registry = self.load_system_registry(system_path)
        framework = self.load_control_framework(framework_path)

        system = system_registry["system"]
        system_id = system["id"]
        system_name = system["name"]
        framework_name = framework["framework"]

        integration = system.get("integration", {})
        agent_id = integration.get("agent_id")
        session_id_pattern = integration.get("session_id_pattern")

        events = self.query_trace_store(agent_id=agent_id)

        if session_id_pattern:
            import re

            pattern = re.escape(session_id_pattern).replace(r"\*", ".*")
            events = [e for e in events if re.fullmatch(pattern, e.get("session_id", ""))]

        integrity = self.check_integrity(agent_id)
        provider_role = system.get("provider_role")
        risk_class = system.get("risk_class")
        # A control is "declared" when the registry asserts the framework it
        # belongs to. That is a weak signal on purpose — it is exactly the
        # self-assertion the DECLARED tier exists to keep separate from
        # observed behaviour.
        declared_frameworks = set((system.get("controls") or {}).get("frameworks") or [])
        declared = bool(declared_frameworks)

        controls_evidence = []
        for article in framework.get("articles", []):
            for control in article.get("controls", []):
                controls_evidence.append(
                    self.match_events_to_control(
                        events,
                        control,
                        provider_role=provider_role,
                        risk_class=risk_class,
                        integrity=integrity,
                        declared=declared,
                    )
                )

        applicable = [
            c
            for c in controls_evidence
            if not c.not_yet_applicable and not c.not_applicable_to_role
        ]

        # Deliberately no `satisfaction_rate_percent`. A single number cannot
        # distinguish a declaration from an observation, and publishing one is
        # how a field-presence check becomes a conformity claim (P10, gap G4).
        summary = {
            "total_controls": len(controls_evidence),
            "applicable_controls": len(applicable),
            "not_yet_applicable": sum(1 for c in controls_evidence if c.not_yet_applicable),
            "not_applicable_to_role": sum(1 for c in controls_evidence if c.not_applicable_to_role),
            "controls_with_violations": sum(1 for c in applicable if c.violations),
            "events_analyzed": len(events),
            "integrity": str(integrity),
        }

        return ComplianceReport(
            system_id=system_id,
            system_name=system_name,
            framework=framework_name,
            controls=controls_evidence,
            summary=summary,
        )


def main() -> None:
    """CLI entry point for evidence linker."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Link TrustLayer trace events to compliance controls"
    )
    parser.add_argument(
        "--system",
        type=Path,
        required=True,
        help="Path to system registry YAML",
    )
    parser.add_argument(
        "--framework",
        type=Path,
        required=True,
        help="Path to control framework YAML",
    )
    parser.add_argument(
        "--trace-store-url",
        type=str,
        default="http://127.0.0.1:8089",
        help="TrustLayer trace store URL",
    )
    parser.add_argument(
        "--api-token",
        type=str,
        default=None,
        help="API token for authentication",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file for JSON report (default: stdout)",
    )
    parser.add_argument(
        "--min-assurance",
        choices=[str(t) for t in AssuranceTier],
        default=None,
        help=(
            "Exit non-zero unless every applicable control reaches this tier. "
            "Use 'evidenced' to require runtime evidence rather than declarations."
        ),
    )

    args = parser.parse_args()

    linker = EvidenceLinker(
        trace_store_url=args.trace_store_url,
        api_token=args.api_token,
    )

    report = linker.generate_compliance_report(
        system_path=args.system,
        framework_path=args.framework,
    )

    report_json = json.dumps(report.to_dict(), indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_json)
        print(f"Report written to {args.output}")
    else:
        print(report_json)

    if args.min_assurance:
        floor = AssuranceTier(args.min_assurance)
        shortfall = [
            c
            for c in report.controls
            if not c.not_yet_applicable
            and not c.not_applicable_to_role
            and not tier_at_least(c.assurance, floor)
        ]
        if shortfall:
            print(
                f"{len(shortfall)} control(s) below assurance tier {floor}: "
                + ", ".join(f"{c.control_id}={c.assurance}" for c in shortfall[:10]),
                file=sys.stderr,
            )
            raise SystemExit(1)


if __name__ == "__main__":
    main()
