"""Generates a compliance audit package as Markdown + JSON.

Reads system registries, control frameworks, and readiness reports
to produce a human- and auditor-readable audit package.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from compliance.src.evidence_linker import EvidenceLinker
from compliance.src.readiness_scanner import ReadinessScanner


def _flatten_controls(framework: dict[str, Any]) -> list[dict[str, Any]]:
    """Controls live under ``articles[].controls[]``, not at the top level."""
    controls: list[dict[str, Any]] = []
    for article in framework.get("articles", []):
        controls.extend(article.get("controls", []))
    return controls + framework.get("controls", [])


#: How many events an audit package examines per system.
#:
#: ``EvidenceLinker`` defaults to 1000, which is a sensible interactive default
#: and the wrong one here: an audit that silently examines the newest thousand
#: events of a system with fifty thousand reports a coverage ratio over a sample
#: while presenting it as the population. Raised, and the package says when the
#: ceiling was reached so a truncated audit is never mistaken for a complete one.
AUDIT_EVENT_LIMIT = 100_000


def _link_runtime_evidence(
    system: dict[str, Any],
    framework_paths: list[Path],
    event_limit: int = AUDIT_EVENT_LIMIT,
) -> dict[str, Any] | None:
    """Match recorded events against this system's controls.

    Returns ``None`` when the system declares no ``trace_store_url`` — an audit
    package for a system with no trace store should say nothing about runtime
    evidence rather than imply there was none to find.

    The readiness scan answers "is this project set up correctly"; it reads a
    directory and never asks what actually ran. Without this, an audit package
    for a system with a live trace store contained no evidence from it, and the
    two halves of the compliance story — configured, and observed — never met.
    """
    trace_store_url = system.get("integration", {}).get("trace_store_url")
    if not trace_store_url:
        return None

    linker = EvidenceLinker(trace_store_url=trace_store_url)
    agent_id = system.get("integration", {}).get("agent_id")
    events = (
        linker.query_trace_store(agent_id=agent_id, limit=event_limit)
        if agent_id
        else linker.query_trace_store(limit=event_limit)
    )

    controls_evidence: list[dict[str, Any]] = []
    for framework_path in framework_paths:
        try:
            framework = linker.load_control_framework(framework_path)
        except Exception as exc:  # noqa: BLE001 - a bad framework file is not an audit failure
            controls_evidence.append(
                {
                    "framework": framework_path.name,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        for control in _flatten_controls(framework):
            if not control.get("evidence_query"):
                # Controls with no query are evidenced by documents, not events.
                # Reporting them here would turn "not this kind of evidence" into
                # "missing evidence", which is a finding they have not earned.
                continue
            evidence = linker.match_events_to_control(events, control)
            # `to_dict()` is the linker's own serialisation. Hand-picking fields
            # here would drift the moment ControlEvidence gains one — it already
            # has, between assurance tiers and violations arriving.
            controls_evidence.append(
                {"framework": framework.get("framework", framework_path.stem), **evidence.to_dict()}
            )

    queried = [item for item in controls_evidence if "outcome" in item]
    satisfied = sum(1 for item in queried if item["outcome"] == "satisfied")
    # Kept apart from unsatisfied on purpose, mirroring QueryOutcome: "we cannot
    # tell" and "we checked and it failed" call for different actions, and an
    # audit package that merges them hands an auditor a failure where there is a
    # blind spot.
    indeterminate = sum(1 for item in queried if item["outcome"] == "indeterminate")

    return {
        "trace_store_url": trace_store_url,
        "agent_id": agent_id,
        "events_examined": len(events),
        "event_limit": event_limit,
        # Reaching the ceiling means the population is a window, and every
        # coverage ratio below is computed over that window rather than over the
        # system's history. An auditor cannot infer this from the numbers.
        "events_truncated": len(events) >= event_limit,
        # An empty event list is ambiguous by construction: EvidenceLinker
        # catches every HTTP error and returns []. Saying so here stops a
        # reachability failure from being read as a finding about the system.
        "events_note": (
            "no events returned — the trace store may be unreachable, or the "
            "system may have recorded nothing. EvidenceLinker cannot distinguish these."
            if not events
            else None
        ),
        "controls_evidenced": satisfied,
        "controls_indeterminate": indeterminate,
        "controls_queried": len(queried),
        "controls": controls_evidence,
    }


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
                "runtime_evidence": _link_runtime_evidence(system, framework_paths),
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

        runtime = system.get("runtime_evidence")
        if runtime:
            lines.extend(
                [
                    "### Runtime Evidence",
                    "",
                    f"Matched against `{runtime['trace_store_url']}` — "
                    f"{runtime['events_examined']} event(s) examined, "
                    f"{runtime['controls_evidenced']}/{runtime['controls_queried']} "
                    "queryable control(s) evidenced"
                    + (
                        f", {runtime['controls_indeterminate']} indeterminate."
                        if runtime["controls_indeterminate"]
                        else "."
                    ),
                    "",
                ]
            )
            if runtime.get("events_truncated"):
                lines.extend(
                    [
                        (
                            f"> ⚠️ Examined the {runtime['event_limit']} most recent events, "
                            "which is the ceiling — older events were not considered, and the "
                            "ratios below describe that window rather than the whole history."
                        ),
                        "",
                    ]
                )
            if runtime.get("events_note"):
                # An empty result is ambiguous by construction and must not be
                # read as a finding about the system.
                lines.extend([f"> ⚠️ {runtime['events_note']}", ""])
            if runtime["controls"]:
                lines.extend(
                    [
                        "| Status | Control | Events | Note |",
                        "|--------|---------|--------|------|",
                    ]
                )
                for item in runtime["controls"]:
                    if "error" in item:
                        lines.append(
                            f"| ❓ | `{item['framework']}` | — | could not load: {item['error']} |"
                        )
                        continue
                    outcome = item.get("outcome", "indeterminate")
                    icon = {"satisfied": "✅", "unsatisfied": "❌"}.get(outcome, "❓")
                    note = "" if outcome == "satisfied" else (item.get("gap_reason") or outcome)
                    lines.append(
                        f"| {icon} | {item['control_id']} — {item['control_title']} | "
                        f"{item.get('satisfied_count', 0)}/{item.get('population', 0)} | {note} |"
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
