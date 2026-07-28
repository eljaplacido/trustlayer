"""Compliance graph generator — extends Hermes with compliance nodes.

Generates markdown files in the Obsidian vault under `07_Compliance/`
that link AI systems, controls, evidence, and frameworks via wikilinks.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

_compliance_src = Path(__file__).resolve().parent.parent.parent / "compliance" / "src"
if str(_compliance_src) not in sys.path:
    sys.path.insert(0, str(_compliance_src))
ReadinessScanner = importlib.import_module("readiness_scanner").ReadinessScanner


def generate_compliance_graph(
    vault_path: Path,
    project_dirs: list[Path],
    framework_paths: list[Path] | None = None,
) -> dict[str, int]:
    """Generate compliance graph markdown files in Obsidian vault.

    Args:
        vault_path: Path to Obsidian vault root
        project_dirs: Project directories to scan
        framework_paths: Optional paths to control frameworks

    Returns:
        Counts of generated files
    """
    if framework_paths is None:
        framework_paths = []

    compliance_dir = vault_path / "07_Compliance"
    systems_dir = compliance_dir / "systems"
    controls_dir = compliance_dir / "controls"
    frameworks_dir = compliance_dir / "frameworks"

    for d in [systems_dir, controls_dir, frameworks_dir]:
        d.mkdir(parents=True, exist_ok=True)

    counts = {"systems": 0, "controls": 0, "frameworks": 0, "total_notes": 0}

    framework_index_links = []

    for fw_path in framework_paths:
        if not fw_path.exists():
            continue
        with open(fw_path) as f:
            fw_data = yaml.safe_load(f)
        fw_name = fw_data.get("framework", fw_path.stem)
        framework_file = frameworks_dir / f"{_safe_filename(fw_name)}.md"

        fw_article_links = []
        for article in fw_data.get("articles", []):
            article_id = article["id"]
            article_title = article["title"]
            article_file = controls_dir / f"{_safe_filename(article_id)}.md"

            control_links = []
            for control in article.get("controls", []):
                control_id = control["id"]
                control_links.append(
                    f"- **{control_id}** — {control['title']} "
                    f"({'mandatory' if control.get('mandatory', True) else 'optional'}, "
                    f"{control.get('priority', 'medium')})"
                )

            _write_note(
                article_file,
                title=f"{article_id} — {article_title}",
                properties={
                    "type": "compliance_control",
                    "framework": fw_name,
                    "article_id": article_id,
                    "date": datetime.now(UTC).strftime("%Y-%m-%d"),
                },
                body=(
                    f"# {article_id} — {article_title}\n\n"
                    f"**Framework:** [[{_safe_filename(fw_name)}]]\n\n"
                    f"{article.get('description', '')}\n\n"
                    f"## Controls\n\n" + "\n".join(control_links)
                ),
            )
            counts["controls"] += 1
            fw_article_links.append(
                f"- [[{_safe_filename(article_id)}|{article_id} – {article_title}]]"
            )

        _write_note(
            framework_file,
            title=(f"{fw_name} — {fw_data.get('description', '').split('.')[0].strip('.')}"),
            properties={
                "type": "compliance_framework",
                "framework": fw_name,
                "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            },
            body=(
                f"# {fw_name}\n\n"
                f"{fw_data.get('description', '')}\n\n"
                f"## Articles\n\n" + "\n".join(fw_article_links)
            ),
        )
        counts["frameworks"] += 1
        framework_index_links.append(f"- [[{_safe_filename(fw_name)}|{fw_name}]]")

    system_links = []
    for project_dir in project_dirs:
        scanner = ReadinessScanner(project_dir=project_dir)
        registry = scanner.load_system_registry()
        if not registry:
            continue

        system = registry["system"]
        system_id = system["id"]
        system_file = systems_dir / f"{_safe_filename(system_id)}.md"

        system_report = scanner.scan_readiness()

        check_rows = []
        for c in system_report.checks:
            status_icon = {
                "PASS": "✓",
                "FAIL": "✗",
                "GAP": "!",
                "SKIP": "-",
            }.get(c.status, "?")
            check_rows.append(
                f"| {status_icon} {c.status} | {c.check_title} | {c.priority} | {c.details} |"
            )

        readiness = system_report.summary
        score = readiness.get("readiness_score_percent", 0)

        _write_note(
            system_file,
            title=system["name"],
            properties={
                "type": "compliance_system",
                "system_id": system_id,
                "risk_class": system.get("risk_class", "unknown"),
                "readiness_score": score,
                "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            },
            body=(
                f"# {system['name']}\n\n"
                f"**System ID:** `{system_id}`\n"
                f"**Risk Class:** {system.get('risk_class', 'unknown')}\n"
                f"**Provider Role:** {system.get('provider_role', 'unknown')}\n"
                f"**Domain:** {system.get('domain', 'unknown')}\n\n"
                f"## Readiness: {score}%\n\n"
                f"- Passed: {readiness.get('passed', 0)}\n"
                f"- Failed: {readiness.get('failed', 0)}\n"
                f"- Gaps: {readiness.get('gaps', 0)}\n\n"
                f"## Checks\n\n"
                f"| Status | Check | Priority | Details |\n"
                f"|--------|-------|----------|---------|\n" + "\n".join(check_rows) + "\n\n"
                "## Frameworks Applied\n\n"
                + "\n".join(
                    f"- [[{_safe_filename(fw)}]]"
                    for fw in system.get("controls", {}).get("frameworks", [])
                )
            ),
        )
        counts["systems"] += 1
        system_links.append(f"- [[{_safe_filename(system_id)}|{system['name']}]] ({score}%)")

    index_file = compliance_dir / "Compliance Index.md"
    _write_note(
        index_file,
        title="Compliance Index",
        properties={
            "type": "compliance_index",
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        },
        body=(
            "# Compliance Index\n\n"
            f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"## AI Systems ({counts['systems']})\n\n"
            + ("\n".join(system_links) if system_links else "No systems registered.\n")
            + f"\n\n## Frameworks ({counts['frameworks']})\n\n"
            + (
                "\n".join(framework_index_links)
                if framework_index_links
                else "No frameworks registered.\n"
            )
            + f"\n\n## Control Articles ({counts['controls']})\n\n"
            + "See individual framework pages for article breakdowns.\n"
        ),
    )
    counts["total_notes"] = counts["systems"] + counts["controls"] + counts["frameworks"] + 1

    return counts


def _safe_filename(name: str) -> str:
    """Create a safe filename from a string."""
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name)
    return safe.strip()


def _write_note(path: Path, title: str, properties: dict[str, Any], body: str) -> None:
    """Write an Obsidian note with YAML frontmatter."""
    properties_str = json.dumps(properties, indent=2)
    content = f"---\ntitle: {title}\n{properties_str}\n---\n\n{body}"

    with open(path, "w") as f:
        f.write(content)


def main() -> None:
    """CLI entry point for compliance graph generator."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate compliance graph in Obsidian vault")
    parser.add_argument(
        "--vault",
        type=Path,
        required=True,
        help="Path to Obsidian vault root",
    )
    parser.add_argument(
        "--project-dirs",
        nargs="+",
        type=Path,
        required=True,
        help="Project directories to scan",
    )
    parser.add_argument(
        "--frameworks",
        nargs="+",
        type=Path,
        default=None,
        help="Control framework files",
    )

    args = parser.parse_args()

    counts = generate_compliance_graph(
        vault_path=args.vault,
        project_dirs=args.project_dirs,
        framework_paths=args.frameworks,
    )

    print(f"Generated {counts['total_notes']} notes:")
    print(f"  Systems: {counts['systems']}")
    print(f"  Controls: {counts['controls']}")
    print(f"  Frameworks: {counts['frameworks']}")
    print("  Index: 1")
    print(f"\nVault path: {args.vault / '07_Compliance'}")


if __name__ == "__main__":
    main()
