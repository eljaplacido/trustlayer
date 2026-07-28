"""
Readiness Scanner - CLI tool for checking AI system production readiness.

This tool scans a project directory and checks if the AI system meets
the requirements defined in control frameworks (EU AI Act, Aitomation template, etc.).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from compliance.src.validation import load_yaml_mapping, validate_document


@dataclass
class ReadinessCheck:
    """Result of a single readiness check."""

    check_id: str
    check_title: str
    status: str  # PASS, FAIL, GAP, SKIP
    details: str
    priority: str = "medium"


@dataclass
class ReadinessReport:
    """Readiness report for an AI system."""

    system_id: str
    system_name: str
    checks: list[ReadinessCheck]
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "system_id": self.system_id,
            "system_name": self.system_name,
            "checks": [
                {
                    "check_id": c.check_id,
                    "check_title": c.check_title,
                    "status": c.status,
                    "details": c.details,
                    "priority": c.priority,
                }
                for c in self.checks
            ],
            "summary": self.summary,
        }

    def print_summary(self) -> None:
        """Print human-readable summary."""
        print(f"\n{'=' * 70}")
        print(f"Readiness Report: {self.system_name} ({self.system_id})")
        print(f"{'=' * 70}\n")

        for check in self.checks:
            status_icon = {
                "PASS": "✓",
                "FAIL": "✗",
                "GAP": "!",
                "SKIP": "-",
            }.get(check.status, "?")

            priority_marker = {
                "critical": "!!!",
                "high": "!!",
                "medium": "!",
                "low": "",
            }.get(check.priority, "")

            print(f"{status_icon} {check.status:4s} {priority_marker:3s} {check.check_id}")
            print(f"  {check.check_title}")
            print(f"  {check.details}\n")

        print(f"{'=' * 70}")
        print("Summary:")
        print(f"  Total checks: {self.summary.get('total_checks', 0)}")
        print(f"  Passed: {self.summary.get('passed', 0)}")
        print(f"  Failed: {self.summary.get('failed', 0)}")
        print(f"  Gaps: {self.summary.get('gaps', 0)}")
        print(f"  Skipped: {self.summary.get('skipped', 0)}")
        print(f"  Readiness score: {self.summary.get('readiness_score_percent', 0):.1f}%")
        print(f"{'=' * 70}\n")


class ReadinessScanner:
    """Scans AI systems for production readiness."""

    def __init__(self, project_dir: Path) -> None:
        """Initialize readiness scanner.

        Args:
            project_dir: Path to project directory
        """
        self.project_dir = project_dir

    def load_system_registry(self) -> dict[str, Any] | None:
        """Load system registry from project directory.

        Returns:
            System registry dictionary or None if not found
        """
        possible_paths = [
            self.project_dir / "system.yaml",
            self.project_dir / "system.yml",
            self.project_dir / "compliance" / "system.yaml",
            self.project_dir / ".trustlayer" / "system.yaml",
        ]

        for path in possible_paths:
            if path.exists():
                registry = load_yaml_mapping(path)
                validate_document(registry, "system.schema.json")
                return registry

        return None

    def check_file_exists(self, filename: str) -> bool:
        """Check if a file exists in project directory.

        Args:
            filename: Filename to check

        Returns:
            True if file exists
        """
        return (self.project_dir / filename).exists()

    def check_directory_exists(self, dirname: str) -> bool:
        """Check if a directory exists in project directory.

        Args:
            dirname: Directory name to check

        Returns:
            True if directory exists
        """
        return (self.project_dir / dirname).is_dir()

    def scan_readiness(
        self,
        framework_path: Path | None = None,
    ) -> ReadinessReport:
        """Scan project for readiness.

        Args:
            framework_path: Optional path to control framework YAML

        Returns:
            ReadinessReport with check results
        """
        system_registry = self.load_system_registry()

        if not system_registry:
            return ReadinessReport(
                system_id="unknown",
                system_name="Unknown System",
                checks=[
                    ReadinessCheck(
                        check_id="system-registry",
                        check_title="System Registry",
                        status="FAIL",
                        details="No system.yaml found in project directory",
                        priority="critical",
                    )
                ],
                summary={
                    "total_checks": 1,
                    "passed": 0,
                    "failed": 1,
                    "gaps": 0,
                    "skipped": 0,
                    "readiness_score_percent": 0.0,
                },
            )

        system = system_registry["system"]
        system_id = system["id"]
        system_name = system["name"]

        checks: list[ReadinessCheck] = []

        checks.append(
            ReadinessCheck(
                check_id="system-registry",
                check_title="System Registry",
                status="PASS",
                details=f"System registry found: {system_name}",
                priority="critical",
            )
        )

        if system.get("risk_class"):
            checks.append(
                ReadinessCheck(
                    check_id="risk-classification",
                    check_title="Risk Classification",
                    status="PASS",
                    details=f"Risk class: {system['risk_class']}",
                    priority="critical",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    check_id="risk-classification",
                    check_title="Risk Classification",
                    status="FAIL",
                    details="Risk class not defined in system registry",
                    priority="critical",
                )
            )

        if system.get("intended_purpose") or system.get("approved_use_cases"):
            checks.append(
                ReadinessCheck(
                    check_id="intended-purpose",
                    check_title="Intended Purpose",
                    status="PASS",
                    details="Intended purpose or approved use cases defined",
                    priority="critical",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    check_id="intended-purpose",
                    check_title="Intended Purpose",
                    status="GAP",
                    details="Intended purpose not clearly defined",
                    priority="critical",
                )
            )

        if system.get("owner"):
            owner = system["owner"]
            if owner.get("business") and owner.get("technical"):
                checks.append(
                    ReadinessCheck(
                        check_id="ownership",
                        check_title="Ownership",
                        status="PASS",
                        details=f"Business: {owner['business']}, Technical: {owner['technical']}",
                        priority="high",
                    )
                )
            else:
                checks.append(
                    ReadinessCheck(
                        check_id="ownership",
                        check_title="Ownership",
                        status="GAP",
                        details="Ownership partially defined",
                        priority="high",
                    )
                )
        else:
            checks.append(
                ReadinessCheck(
                    check_id="ownership",
                    check_title="Ownership",
                    status="FAIL",
                    details="No ownership defined",
                    priority="high",
                )
            )

        if system.get("data_classes"):
            checks.append(
                ReadinessCheck(
                    check_id="data-classification",
                    check_title="Data Classification",
                    status="PASS",
                    details=f"Data classes: {', '.join(system['data_classes'])}",
                    priority="critical",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    check_id="data-classification",
                    check_title="Data Classification",
                    status="GAP",
                    details="Data classes not defined",
                    priority="critical",
                )
            )

        integration = system.get("integration", {})
        if integration.get("agent_id"):
            checks.append(
                ReadinessCheck(
                    check_id="trace-integration",
                    check_title="Trace Integration",
                    status="PASS",
                    details=f"Agent ID: {integration['agent_id']}",
                    priority="high",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    check_id="trace-integration",
                    check_title="Trace Integration",
                    status="GAP",
                    details="Agent ID not configured for trace integration",
                    priority="high",
                )
            )

        if integration.get("guardian_policy"):
            checks.append(
                ReadinessCheck(
                    check_id="guardian-policy",
                    check_title="Guardian Policy",
                    status="PASS",
                    details=f"Policy: {integration['guardian_policy']}",
                    priority="high",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    check_id="guardian-policy",
                    check_title="Guardian Policy",
                    status="GAP",
                    details="Guardian policy not configured",
                    priority="high",
                )
            )

        if system.get("human_oversight"):
            oversight = system["human_oversight"]
            if oversight.get("type") and oversight.get("approval_points"):
                checks.append(
                    ReadinessCheck(
                        check_id="human-oversight",
                        check_title="Human Oversight",
                        status="PASS",
                        details=f"Type: {oversight['type']}, Approval points: {len(oversight['approval_points'])}",
                        priority="critical",
                    )
                )
            else:
                checks.append(
                    ReadinessCheck(
                        check_id="human-oversight",
                        check_title="Human Oversight",
                        status="GAP",
                        details="Human oversight partially defined",
                        priority="critical",
                    )
                )
        else:
            checks.append(
                ReadinessCheck(
                    check_id="human-oversight",
                    check_title="Human Oversight",
                    status="FAIL",
                    details="Human oversight not defined",
                    priority="critical",
                )
            )

        doc_patterns = ["README.md", "ARCHITECTURE.md", "docs/", "**/docs/"]
        found_docs = [
            f
            for f in doc_patterns
            if self.check_file_exists(f)
            or self.check_directory_exists(f)
            or any(self.project_dir.glob(f))
        ]
        if found_docs:
            checks.append(
                ReadinessCheck(
                    check_id="documentation",
                    check_title="Documentation",
                    status="PASS",
                    details=f"Found: {', '.join(found_docs)}",
                    priority="high",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    check_id="documentation",
                    check_title="Documentation",
                    status="GAP",
                    details="No standard documentation files found",
                    priority="high",
                )
            )

        test_patterns = ["tests/", "test/", "**/tests/", "**/test/"]
        found_tests = [
            d
            for d in test_patterns
            if self.check_directory_exists(d) or any(self.project_dir.glob(d))
        ]
        if found_tests:
            checks.append(
                ReadinessCheck(
                    check_id="testing",
                    check_title="Testing",
                    status="PASS",
                    details=f"Test directory found: {', '.join(found_tests)}",
                    priority="high",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    check_id="testing",
                    check_title="Testing",
                    status="GAP",
                    details="No test directory found",
                    priority="high",
                )
            )

        # Article 50 transparency checks
        article_50 = system.get("article_50", {})

        if article_50:
            # Resolve nested disclosure_config with flat-field fallback
            disclosure_config = article_50.get("disclosure_config")
            if disclosure_config is None:
                disclosure_config = article_50

            # 50.1 - Interaction disclosure
            if disclosure_config.get("disclose_ai_interaction") is True:
                checks.append(
                    ReadinessCheck(
                        check_id="art-50.1",
                        check_title="Art 50.1: AI Interaction Disclosure",
                        status="PASS",
                        details="AI interaction disclosure enabled",
                        priority="critical",
                    )
                )
            elif disclosure_config.get("disclosure_mechanism"):
                # Legacy flat field fallback
                checks.append(
                    ReadinessCheck(
                        check_id="art-50.1",
                        check_title="Art 50.1: AI Interaction Disclosure",
                        status="PASS",
                        details=f"Disclosure mechanism: {disclosure_config['disclosure_mechanism']}",
                        priority="critical",
                    )
                )
            else:
                checks.append(
                    ReadinessCheck(
                        check_id="art-50.1",
                        check_title="Art 50.1: AI Interaction Disclosure",
                        status="GAP",
                        details="No disclosure mechanism defined for human-AI interaction",
                        priority="critical",
                    )
                )

            # 50.2 - Biometric/emotion recognition
            biometric_disclosed = (
                disclosure_config.get("disclose_biometric_classification") is True
                or disclosure_config.get("disclose_emotion_recognition") is True
            )
            biometric_handling = article_50.get("biometric_handling")
            has_biometric_config = biometric_disclosed or (
                biometric_handling and biometric_handling.get("consent_mechanism")
            )
            if has_biometric_config:
                if biometric_handling and biometric_handling.get("consent_mechanism"):
                    details = f"Consent mechanism: {biometric_handling['consent_mechanism']}"
                else:
                    details = "Biometric/emotion disclosure flags configured"
                checks.append(
                    ReadinessCheck(
                        check_id="art-50.2",
                        check_title="Art 50.2: Biometric/Emotion Disclosure",
                        status="PASS",
                        details=details,
                        priority="critical",
                    )
                )
            else:
                # Only flag if system handles sensitive data
                data_cats = article_50.get("data_categories", [])
                if not data_cats:
                    # Fall back to data_classes from top-level system
                    data_cats = system.get("data_classes", [])
                if any(
                    c in data_cats
                    for c in ("sensitive", "sensitive_personal_data", "biometric_data")
                ):
                    checks.append(
                        ReadinessCheck(
                            check_id="art-50.2",
                            check_title="Art 50.2: Biometric/Emotion Disclosure",
                            status="GAP",
                            details="Sensitive data detected but no biometric handling policy",
                            priority="critical",
                        )
                    )
                else:
                    checks.append(
                        ReadinessCheck(
                            check_id="art-50.2",
                            check_title="Art 50.2: Biometric/Emotion Disclosure",
                            status="SKIP",
                            details="No biometric/emotion recognition in scope",
                            priority="medium",
                        )
                    )

            # 50.3 - Content marking
            marking_config = article_50.get("marking_config")
            if marking_config is None:
                marking_config = article_50

            content_marked = marking_config.get("mark_generated_content") is True
            content_labelling = marking_config.get("content_labelling")
            generates_synthetic = marking_config.get("generates_synthetic_content") is True

            if content_marked or content_labelling:
                if content_labelling:
                    details = f"Labelling: {content_labelling}"
                else:
                    details = "Machine-readable content marking enabled"
                checks.append(
                    ReadinessCheck(
                        check_id="art-50.3",
                        check_title="Art 50.3: Content Marking",
                        status="PASS",
                        details=details,
                        priority="critical",
                    )
                )
            else:
                if generates_synthetic:
                    checks.append(
                        ReadinessCheck(
                            check_id="art-50.3",
                            check_title="Art 50.3: Content Marking",
                            status="GAP",
                            details="Generates synthetic content but no labelling mechanism",
                            priority="critical",
                        )
                    )
                else:
                    checks.append(
                        ReadinessCheck(
                            check_id="art-50.3",
                            check_title="Art 50.3: Content Marking",
                            status="SKIP",
                            details="No synthetic content generation in scope",
                            priority="medium",
                        )
                    )
        else:
            # No article_50 block - check if system is potentially in scope
            checks.append(
                ReadinessCheck(
                    check_id="art-50.1",
                    check_title="Art 50.1: AI Interaction Disclosure",
                    status="SKIP",
                    details="article_50 block not defined in system registry",
                    priority="medium",
                )
            )
            checks.append(
                ReadinessCheck(
                    check_id="art-50.2",
                    check_title="Art 50.2: Biometric/Emotion Disclosure",
                    status="SKIP",
                    details="article_50 block not defined in system registry",
                    priority="medium",
                )
            )
            checks.append(
                ReadinessCheck(
                    check_id="art-50.3",
                    check_title="Art 50.3: Content Marking",
                    status="SKIP",
                    details="article_50 block not defined in system registry",
                    priority="medium",
                )
            )

        passed = sum(1 for c in checks if c.status == "PASS")
        failed = sum(1 for c in checks if c.status == "FAIL")
        gaps = sum(1 for c in checks if c.status == "GAP")
        skipped = sum(1 for c in checks if c.status == "SKIP")
        total = len(checks)

        readiness_score = (
            (passed / (total - skipped) * 100)
            if (total - skipped) > 0
            else (100.0 if passed > 0 else 0.0)
        )

        summary = {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "gaps": gaps,
            "skipped": skipped,
            "readiness_score_percent": round(readiness_score, 2),
        }

        return ReadinessReport(
            system_id=system_id,
            system_name=system_name,
            checks=checks,
            summary=summary,
        )


def main() -> None:
    """CLI entry point for readiness scanner."""
    import argparse

    parser = argparse.ArgumentParser(description="Scan AI system for production readiness")
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Path to project directory (default: current directory)",
    )
    parser.add_argument(
        "--framework",
        type=Path,
        default=None,
        help="Path to control framework YAML (optional)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file for JSON report (default: stdout)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress human-readable output, only print JSON",
    )

    args = parser.parse_args()

    scanner = ReadinessScanner(project_dir=args.project_dir)
    report = scanner.scan_readiness(framework_path=args.framework)

    if not args.quiet:
        report.print_summary()

    report_json = json.dumps(report.to_dict(), indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report_json)
        if not args.quiet:
            print(f"Report written to {args.output}")
    else:
        if args.quiet:
            print(report_json)

    if report.summary.get("failed", 0) > 0:
        sys.exit(1)
    elif report.summary.get("gaps", 0) > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
