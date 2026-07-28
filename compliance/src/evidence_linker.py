"""
Evidence Linker - Links TrustLayer trace events to compliance controls.

This module queries the TrustLayer trace store and matches events to
controls defined in control frameworks (EU AI Act, Aitomation template, etc.).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from compliance.src.validation import load_yaml_mapping, validate_document


@dataclass
class ControlEvidence:
    """Evidence found for a specific control."""

    control_id: str
    control_title: str
    satisfied: bool
    evidence_count: int
    evidence_samples: list[dict[str, Any]] = field(default_factory=list)
    gap_reason: str | None = None


@dataclass
class ComplianceReport:
    """Compliance report for an AI system."""

    system_id: str
    system_name: str
    framework: str
    controls: list[ControlEvidence]
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "system_id": self.system_id,
            "system_name": self.system_name,
            "framework": self.framework,
            "controls": [
                {
                    "control_id": c.control_id,
                    "control_title": c.control_title,
                    "satisfied": c.satisfied,
                    "evidence_count": c.evidence_count,
                    "evidence_samples": c.evidence_samples[:5],
                    "gap_reason": c.gap_reason,
                }
                for c in self.controls
            ],
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

    def match_events_to_control(
        self,
        events: list[dict[str, Any]],
        control: dict[str, Any],
    ) -> ControlEvidence:
        """Match trace events to a specific control.

        Args:
            events: List of trace events
            control: Control definition from framework

        Returns:
            ControlEvidence with match results
        """
        control_id = control["id"]
        control_title = control["title"]
        evidence_query = control.get("evidence_query")

        if not evidence_query:
            return ControlEvidence(
                control_id=control_id,
                control_title=control_title,
                satisfied=False,
                evidence_count=0,
                gap_reason="No evidence query defined for this control",
            )

        event_types = evidence_query.get("event_types", [])
        payload_filters = evidence_query.get("payload_filters", {})
        min_count = evidence_query.get("min_count", 1)

        matching_events = []
        for event in events:
            if event_types and event.get("event_type") not in event_types:
                continue

            if payload_filters:
                payload = event.get("payload", {})
                match = True
                for key, value in payload_filters.items():
                    if payload.get(key) != value:
                        match = False
                        break
                if not match:
                    continue

            matching_events.append(event)

        satisfied = len(matching_events) >= min_count
        gap_reason = None
        if not satisfied:
            gap_reason = f"Found {len(matching_events)} events, need at least {min_count}"

        return ControlEvidence(
            control_id=control_id,
            control_title=control_title,
            satisfied=satisfied,
            evidence_count=len(matching_events),
            evidence_samples=matching_events[:10],
            gap_reason=gap_reason,
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

        controls_evidence = []
        for article in framework.get("articles", []):
            for control in article.get("controls", []):
                evidence = self.match_events_to_control(events, control)
                controls_evidence.append(evidence)

        satisfied_count = sum(1 for c in controls_evidence if c.satisfied)
        total_count = len(controls_evidence)
        satisfaction_rate = (satisfied_count / total_count * 100) if total_count > 0 else 0

        summary = {
            "total_controls": total_count,
            "satisfied_controls": satisfied_count,
            "unsatisfied_controls": total_count - satisfied_count,
            "satisfaction_rate_percent": round(satisfaction_rate, 2),
            "events_analyzed": len(events),
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


if __name__ == "__main__":
    main()
