"""
Report generator for the compliance dashboard pane.

Generates a JSON report that combines readiness scanner output from
multiple AI systems into a single dashboard-consumable format.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from compliance.src.readiness_scanner import ReadinessScanner


def generate_dashboard_report(
    project_dirs: list[Path],
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Generate a consolidated compliance report for the dashboard.

    Args:
        project_dirs: List of project directories to scan
        output_path: Optional output path for the JSON report

    Returns:
        Consolidated report dictionary
    """
    systems: list[dict[str, Any]] = []
    total_controls = 0
    total_passed = 0
    total_failed = 0
    total_gaps = 0

    for project_dir in project_dirs:
        scanner = ReadinessScanner(project_dir=project_dir)
        report = scanner.scan_readiness()

        system_data = {
            "system_id": report.system_id,
            "system_name": report.system_name,
            "checks": [
                {
                    "check_id": c.check_id,
                    "check_title": c.check_title,
                    "status": c.status,
                    "details": c.details,
                    "priority": c.priority,
                }
                for c in report.checks
            ],
            "summary": report.summary,
        }
        systems.append(system_data)

        total_controls += report.summary.get("total_checks", 0)
        total_passed += report.summary.get("passed", 0)
        total_failed += report.summary.get("failed", 0)
        total_gaps += report.summary.get("gaps", 0)

    overall_readiness = (total_passed / total_controls * 100) if total_controls > 0 else 0

    report_data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "generator_version": "0.1.0",
        "systems": systems,
        "overall_summary": {
            "total_systems": len(systems),
            "total_controls": total_controls,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_gaps": total_gaps,
            "overall_readiness_percent": round(overall_readiness, 2),
        },
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

    return report_data


def main() -> None:
    """CLI entry point for compliance dashboard report generator."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate compliance dashboard report")
    parser.add_argument(
        "--project-dirs",
        nargs="+",
        type=Path,
        required=True,
        help="Project directories to scan",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file for the dashboard JSON report",
    )

    args = parser.parse_args()

    report = generate_dashboard_report(
        project_dirs=args.project_dirs,
        output_path=args.output,
    )

    if args.output:
        print(f"Dashboard report written to {args.output}")
    else:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
