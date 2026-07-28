"""Generates a compliance audit package as Markdown + JSON.

Reads system registries, control frameworks, and readiness reports
to produce a human- and auditor-readable audit package.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from compliance.src.readiness_scanner import ReadinessScanner


def generate_audit_package(
    project_dirs: list[Path],
    framework_paths: list[Path] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate a full audit package for one or more AI systems.

    Args:
        project_dirs: List of project directories to audit
        framework_paths: Optional paths to control frameworks
        output_dir: Optional output directory

    Returns:
        Audit package dictionary
    """
    if framework_paths is None:
        framework_paths = []

    systems_audit: list[dict[str, Any]] = []
    for project_dir in project_dirs:
        scanner = ReadinessScanner(project_dir=project_dir)
        system_registry = scanner.load_system_registry()

        if not system_registry:
            continue

        system = system_registry["system"]
        report = scanner.scan_readiness()

        checks = []
        for c in report.checks:
            checks.append(
                {
                    "check_id": c.check_id,
                    "check_title": c.check_title,
                    "status": c.status,
                    "details": c.details,
                    "priority": c.priority,
                }
            )

        frameworks_applied = system.get("controls", {}).get("frameworks", [])

        systems_audit.append(
            {
                "system_id": system["id"],
                "system_name": system["name"],
                "risk_class": system.get("risk_class", "unknown"),
                "provider_role": system.get("provider_role", "unknown"),
                "domain": system.get("domain", "unknown"),
                "owner": system.get("owner", {}),
                "data_classes": system.get("data_classes", []),
                "human_oversight": system.get("human_oversight", {}),
                "frameworks_applied": frameworks_applied,
                "readiness": report.summary,
                "checks": checks,
            }
        )

    audit_package = {
        "audit_generated_at": datetime.now(UTC).isoformat(),
        "audit_version": "0.1.0",
        "systems": systems_audit,
        "overall_summary": _compute_overall_summary(systems_audit),
    }

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / "audit-package.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(audit_package, f, indent=2)

        md_path = output_dir / "audit-package.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(_render_audit_markdown(audit_package))

        print(f"Audit package written to {output_dir}")

    return audit_package


def _compute_overall_summary(
    systems_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(systems_audit)
    if total == 0:
        return {"total_systems": 0, "overall_readiness_percent": 0}

    total_checks = 0
    total_passed = 0
    total_failed = 0
    total_gaps = 0

    for system in systems_audit:
        readiness = system["readiness"]
        total_checks += readiness.get("total_checks", 0)
        total_passed += readiness.get("passed", 0)
        total_failed += readiness.get("failed", 0)
        total_gaps += readiness.get("gaps", 0)

    return {
        "total_systems": total,
        "total_checks": total_checks,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_gaps": total_gaps,
        "overall_readiness_percent": round(
            (total_passed / total_checks * 100) if total_checks > 0 else 0, 2
        ),
    }


def _render_audit_markdown(audit: dict[str, Any]) -> str:
    summary = audit["overall_summary"]
    lines = [
        "# AI Systems Compliance Audit Package",
        "",
        f"**Generated:** {audit['audit_generated_at']}",
        f"**Audit Version:** {audit['audit_version']}",
        "",
        "## Overall Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total Systems | {summary['total_systems']} |",
        f"| Total Controls Checked | {summary['total_checks']} |",
        f"| Passed | {summary['total_passed']} |",
        f"| Failed | {summary['total_failed']} |",
        f"| Gaps | {summary['total_gaps']} |",
        f"| Overall Readiness | {summary['overall_readiness_percent']}% |",
        "",
    ]

    for system in audit["systems"]:
        r = system["readiness"]
        score = r.get("readiness_score_percent", 0)
        status_bar = "🟢" if score >= 90 else ("🟡" if score >= 70 else "🔴")

        lines.extend(
            [
                f"## {status_bar} {system['system_name']} (`{system['system_id']}`)",
                "",
                f"- **Risk Class:** {system['risk_class']}",
                f"- **Provider Role:** {system['provider_role']}",
                f"- **Domain:** {system['domain']}",
                f"- **Frameworks:** {', '.join(system.get('frameworks_applied', []))}",
                f"- **Readiness Score:** {score}% ({r.get('passed', 0)}/{r.get('total_checks', 0)} passed, {r.get('failed', 0)} failed, {r.get('gaps', 0)} gaps)",
                "",
                "### Readiness Checks",
                "",
                "| Status | Check | Priority | Details |",
                "|--------|-------|----------|---------|",
            ]
        )

        for check in system["checks"]:
            status_icon = {
                "PASS": "✅",
                "FAIL": "❌",
                "GAP": "⚠️",
                "SKIP": "➖",
            }.get(check["status"], "❓")

            lines.append(
                f"| {status_icon} {check['status']} | {check['check_title']} | "
                f"{check['priority']} | {check['details']} |",
            )

        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "*This audit package was generated by TrustLayer Compliance Framework.*",
            "*Run `python compliance/src/audit_generator.py` to regenerate.*",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    """CLI entry point for audit package generator."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate AI systems compliance audit package")
    parser.add_argument(
        "--project-dirs",
        nargs="+",
        type=Path,
        required=True,
        help="Project directories to audit",
    )
    parser.add_argument(
        "--frameworks",
        nargs="+",
        type=Path,
        default=None,
        help="Control framework files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for audit package",
    )

    args = parser.parse_args()

    generate_audit_package(
        project_dirs=args.project_dirs,
        framework_paths=args.frameworks,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
