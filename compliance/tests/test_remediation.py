"""Tests for the remediation planner and the bundled guidance catalog.

Two distinct concerns, deliberately kept apart:

* the **planner** — matching, deduplication, ordering, and honest reporting of
  what it could not cover. Tested against small hand-built catalogs so a change
  to the shipped guidance never breaks a planner test.
* the **catalog** — that the guidance actually shipped is complete against the
  scanner's checks and well-formed. Tested against the real file, because a
  catalog that validates but covers nothing is the failure mode that matters.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from compliance.src.readiness_scanner import ReadinessScanner
from compliance.src.remediation import (
    ACTIONABLE_STATUSES,
    DISCLAIMER,
    Finding,
    Guidance,
    RemediationPlanner,
    default_catalog_path,
    findings_from_evidence,
    findings_from_readiness,
    load_catalog,
    main,
    render_markdown,
)
from compliance.src.validation import load_yaml_mapping, validate_document

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- helpers ---------------------------------------------------------------


def guidance(
    guidance_id: str,
    *,
    dimension: str = "technical",
    check_ids: tuple[str, ...] = (),
    control_ids: tuple[str, ...] = (),
    blocking: bool = False,
    effort: str = "M",
    statuses: frozenset[str] | None = None,
) -> Guidance:
    return Guidance(
        id=guidance_id,
        title=f"Do {guidance_id}",
        dimension=dimension,  # type: ignore[arg-type]
        why="because",
        steps=("step one",),
        check_ids=frozenset(check_ids),
        control_ids=frozenset(control_ids),
        statuses=statuses if statuses is not None else ACTIONABLE_STATUSES,
        blocking=blocking,
        effort=effort,
    )


def finding(
    finding_id: str,
    *,
    status: str = "GAP",
    priority: str = "medium",
    source: str = "readiness",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        title=finding_id,
        status=status,
        details="detail",
        priority=priority,
        source=source,
    )


# --- finding extraction ----------------------------------------------------


def test_passing_checks_produce_no_findings() -> None:
    """Guidance for something already satisfied buries the work that remains."""
    report = {
        "checks": [
            {"check_id": "a", "check_title": "A", "status": "PASS", "details": ""},
            {"check_id": "b", "check_title": "B", "status": "GAP", "details": ""},
        ]
    }

    findings = findings_from_readiness(report)

    assert [f.finding_id for f in findings] == ["b"]


@pytest.mark.parametrize("status", sorted(ACTIONABLE_STATUSES))
def test_every_actionable_status_is_extracted(status: str) -> None:
    report = {"checks": [{"check_id": "x", "check_title": "X", "status": status, "details": ""}]}

    assert len(findings_from_readiness(report)) == 1


def test_evidence_report_distinguishes_partial_from_missing() -> None:
    """A control with some evidence is a different problem from one with none."""
    report = {
        "controls": [
            {"control_id": "art-12.1", "control_title": "Logs", "satisfied": True},
            {
                "control_id": "art-14.1",
                "control_title": "Oversight",
                "satisfied": False,
                "evidence_count": 3,
            },
            {
                "control_id": "art-50.1",
                "control_title": "Disclosure",
                "satisfied": False,
                "evidence_count": 0,
            },
        ]
    }

    findings = {f.finding_id: f for f in findings_from_evidence(report)}

    assert "art-12.1" not in findings, "a satisfied control is not a finding"
    assert findings["art-14.1"].status == "PARTIAL"
    assert findings["art-50.1"].status == "MISSING"
    assert all(f.source == "evidence" for f in findings.values())


# --- matching --------------------------------------------------------------


def test_guidance_matches_by_check_id_and_by_control_id() -> None:
    planner = RemediationPlanner(
        [guidance("rem-a", check_ids=("chk",)), guidance("rem-b", control_ids=("art-9.1",))],
        "test",
    )

    plan = planner.plan([finding("chk"), finding("art-9.1", source="evidence")])

    assert {i.guidance_id for i in plan.items} == {"rem-a", "rem-b"}


def test_guidance_can_restrict_itself_to_specific_statuses() -> None:
    planner = RemediationPlanner(
        [guidance("rem-a", check_ids=("chk",), statuses=frozenset({"FAIL"}))],
        "test",
    )

    assert planner.plan([finding("chk", status="FAIL")]).items
    assert not planner.plan([finding("chk", status="GAP")]).items


def test_several_findings_converging_on_one_action_emit_it_once() -> None:
    """Missing instrumentation makes many controls unsatisfiable at once.

    Emitting the same work per finding would make a single-cause plan look
    like twenty separate problems.
    """
    planner = RemediationPlanner(
        [guidance("rem-trace", check_ids=("trace",), control_ids=("art-12.1", "art-12.4"))],
        "test",
    )

    plan = planner.plan(
        [
            finding("trace"),
            finding("art-12.1", source="evidence"),
            finding("art-12.4", source="evidence"),
        ]
    )

    assert len(plan.items) == 1
    assert len(plan.items[0].triggered_by) == 3, "every trigger must still be cited"


def test_an_item_takes_the_severity_of_its_most_severe_trigger() -> None:
    """Taking the mildest would let a low-priority match mask a critical one."""
    planner = RemediationPlanner(
        [guidance("rem-a", check_ids=("low-chk", "crit-chk"))],
        "test",
    )

    plan = planner.plan(
        [finding("low-chk", priority="low"), finding("crit-chk", priority="critical")]
    )

    assert plan.items[0].priority == "critical"


# --- honest gaps -----------------------------------------------------------


def test_findings_with_no_guidance_are_reported_not_dropped() -> None:
    """A shorter plan is not a smaller problem."""
    planner = RemediationPlanner([guidance("rem-a", check_ids=("known",))], "test")

    plan = planner.plan([finding("known"), finding("nobody-wrote-this")])

    assert [i.guidance_id for i in plan.items] == ["rem-a"]
    assert [f.finding_id for f in plan.unguided] == ["nobody-wrote-this"]
    assert plan.summary()["unguided_findings"] == 1


def test_unguided_findings_appear_in_the_rendered_plan() -> None:
    planner = RemediationPlanner([], "test")

    markdown = render_markdown(planner.plan([finding("orphan")]))

    assert "orphan" in markdown
    assert "no authored guidance" in markdown


# --- ordering --------------------------------------------------------------


def test_blocking_items_sort_before_everything_else() -> None:
    """Even a cheap critical non-blocker waits behind an expensive blocker.

    A plan that front-loads quick wins while a blocking gap stays open
    optimises for the appearance of progress.
    """
    planner = RemediationPlanner(
        [
            guidance("rem-cheap", check_ids=("a",), blocking=False, effort="S"),
            guidance("rem-blocker", check_ids=("b",), blocking=True, effort="L"),
        ],
        "test",
    )

    plan = planner.plan([finding("a", priority="critical"), finding("b", priority="low")])

    assert [i.guidance_id for i in plan.items] == ["rem-blocker", "rem-cheap"]


def test_within_a_tier_cheaper_work_sorts_first() -> None:
    planner = RemediationPlanner(
        [
            guidance("rem-large", check_ids=("a",), effort="L"),
            guidance("rem-small", check_ids=("b",), effort="S"),
        ],
        "test",
    )

    plan = planner.plan([finding("a"), finding("b")])

    assert [i.guidance_id for i in plan.items] == ["rem-small", "rem-large"]


def test_priority_outranks_effort() -> None:
    planner = RemediationPlanner(
        [
            guidance("rem-big-critical", check_ids=("a",), effort="L"),
            guidance("rem-small-low", check_ids=("b",), effort="S"),
        ],
        "test",
    )

    plan = planner.plan([finding("a", priority="critical"), finding("b", priority="low")])

    assert [i.guidance_id for i in plan.items] == ["rem-big-critical", "rem-small-low"]


def test_plan_is_deterministic() -> None:
    """A plan that reorders between runs cannot be diffed, so it cannot be reviewed."""
    entries = [guidance(f"rem-{c}", check_ids=(c,), effort="M") for c in ("a", "b", "c", "d")]
    planner = RemediationPlanner(entries, "test")
    findings = [finding(c) for c in ("d", "b", "a", "c")]

    first = json.dumps(planner.plan(findings).to_dict(), sort_keys=False)
    second = json.dumps(planner.plan(list(reversed(findings))).to_dict(), sort_keys=False)

    assert first == second


# --- rendering -------------------------------------------------------------


def test_rendered_plan_groups_by_dimension() -> None:
    planner = RemediationPlanner(
        [
            guidance("rem-t", check_ids=("t",), dimension="technical"),
            guidance("rem-d", check_ids=("d",), dimension="documentation"),
            guidance("rem-p", check_ids=("p",), dimension="process"),
        ],
        "test",
    )

    markdown = render_markdown(planner.plan([finding("t"), finding("d"), finding("p")]))

    for heading in ("## Technical", "## Documentation", "## Process"):
        assert heading in markdown


def test_rendered_plan_always_carries_the_disclaimer() -> None:
    """Including on an empty plan — that is exactly when it is most needed."""
    empty = render_markdown(RemediationPlanner([], "test").plan([]))

    assert DISCLAIMER.split(".")[0] in empty
    assert "not a conformity claim" in empty


def test_empty_plan_does_not_read_as_compliant() -> None:
    markdown = render_markdown(RemediationPlanner([], "test").plan([]))

    assert "No actionable findings" in markdown
    assert "not the obligations that apply" in markdown


def test_rendered_item_cites_its_triggers_and_legal_basis() -> None:
    planner = RemediationPlanner.from_catalog(default_catalog_path("eu-ai-act-v1"))

    markdown = render_markdown(planner.plan([finding("trace-integration", status="GAP")]))

    assert "Triggered by:" in markdown
    assert "trace-integration" in markdown
    assert "Art. 12(1)" in markdown


def test_pipe_characters_in_details_do_not_break_the_table() -> None:
    plan = RemediationPlanner([], "test").plan(
        [
            Finding(
                finding_id="odd",
                title="Odd",
                status="GAP",
                details="a | b | c",
                source="readiness",
            )
        ]
    )

    row = next(line for line in render_markdown(plan).splitlines() if "`odd`" in line)

    # Only unescaped pipes delimit cells. Four columns => five delimiters.
    delimiters = len(re.findall(r"(?<!\\)\|", row))
    assert delimiters == 5, f"unescaped pipe broke the row: {row}"
    assert r"a \| b \| c" in row, "the detail text must survive escaping intact"


# --- catalog loading -------------------------------------------------------


def test_catalog_rejects_duplicate_guidance_ids(tmp_path: Path) -> None:
    """A duplicate id would silently shadow one entry and lose its guidance."""
    entry = {
        "id": "rem-dup",
        "title": "T",
        "dimension": "technical",
        "applies_to": {"check_ids": ["x"]},
        "why": "w",
        "steps": ["s"],
    }
    path = tmp_path / "dup.yaml"
    path.write_text(
        json.dumps({"version": "1", "framework": "dup", "guidance": [entry, entry]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate guidance id"):
        load_catalog(path)


def test_catalog_with_a_malformed_entry_raises_rather_than_partially_loading(
    tmp_path: Path,
) -> None:
    """Guidance that silently failed to load produces a plan that looks complete."""
    path = tmp_path / "bad.yaml"
    path.write_text(
        json.dumps(
            {
                "version": "1",
                "framework": "bad",
                "guidance": [
                    {"id": "rem-ok", "title": "T", "dimension": "technical"}  # no why/steps
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(jsonschema.ValidationError):
        load_catalog(path)


def test_omitted_status_list_means_every_actionable_status(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(
        json.dumps(
            {
                "version": "1",
                "framework": "c",
                "guidance": [
                    {
                        "id": "rem-a",
                        "title": "T",
                        "dimension": "technical",
                        "applies_to": {"check_ids": ["x"]},
                        "why": "w",
                        "steps": ["s"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _, entries = load_catalog(path)

    assert entries[0].statuses == ACTIONABLE_STATUSES


def test_schema_forbids_guidance_for_a_passing_check() -> None:
    """PASS is deliberately not a permitted selector."""
    schema_path = REPO_ROOT / "compliance" / "schemas" / "remediation.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    statuses = schema["$defs"]["guidance"]["properties"]["applies_to"]["properties"]["statuses"]

    assert "PASS" not in statuses["items"]["enum"]


# --- the shipped catalog ---------------------------------------------------


def shipped_catalog() -> tuple[str, list[Guidance]]:
    return load_catalog(default_catalog_path("eu-ai-act-v1"))


def test_shipped_catalog_validates() -> None:
    path = default_catalog_path("eu-ai-act-v1")
    validate_document(load_yaml_mapping(path), "remediation.schema.json")


def test_shipped_catalog_covers_every_check_the_scanner_can_emit() -> None:
    """The completeness test that matters.

    A catalog that validates but covers nothing produces an empty plan for a
    system with real gaps — which reads as "nothing to do".
    """
    _, entries = shipped_catalog()
    covered = {check_id for e in entries for check_id in e.check_ids}

    scanner_source = (REPO_ROOT / "compliance" / "src" / "readiness_scanner.py").read_text(
        encoding="utf-8"
    )
    emitted = set(re.findall(r'check_id="([^"]+)"', scanner_source))

    missing = emitted - covered
    assert not missing, f"readiness checks with no remediation guidance: {sorted(missing)}"


def test_shipped_catalog_spans_all_three_dimensions() -> None:
    _, entries = shipped_catalog()
    dimensions = {e.dimension for e in entries}

    assert dimensions == {"technical", "documentation", "process"}


def test_every_shipped_entry_cites_a_legal_basis() -> None:
    """A finding a reader cannot check is a finding they have to trust."""
    _, entries = shipped_catalog()

    missing = [e.id for e in entries if not e.legal_basis]

    assert not missing, f"guidance with no legal basis: {missing}"


def test_every_shipped_entry_says_how_to_verify_it_is_done() -> None:
    """Guidance with no verification produces work nobody can confirm."""
    _, entries = shipped_catalog()

    missing = [e.id for e in entries if not e.verification]

    assert not missing, f"guidance with no verification step: {missing}"


def test_every_shipped_entry_names_an_owner() -> None:
    """The most common reason a gap stays open is that no role owned it."""
    _, entries = shipped_catalog()

    missing = [e.id for e in entries if not e.owner_role]

    assert not missing, f"guidance with no owner_role: {missing}"


def test_every_shipped_entry_selects_something() -> None:
    _, entries = shipped_catalog()

    inert = [e.id for e in entries if not e.check_ids and not e.control_ids]

    assert not inert, f"guidance that can never fire: {inert}"


def test_shipped_catalog_covers_the_article_50_obligations_live_today() -> None:
    """Art. 50(1) has applied since 2026-08-02 — the catalog must speak to it."""
    _, entries = shipped_catalog()
    covered = {c for e in entries for c in e.check_ids}

    assert {"art-50.1", "art-50.2", "art-50.3"} <= covered


# --- end to end ------------------------------------------------------------


def write_system(tmp_path: Path, **overrides: Any) -> Path:
    system: dict[str, Any] = {
        "id": "demo",
        "name": "Demo System",
        "provider_role": "provider",
        "risk_class": "high-risk",
    }
    system.update(overrides)
    project = tmp_path / "project"
    project.mkdir()
    (project / "system.yaml").write_text(json.dumps({"system": system}), encoding="utf-8")
    return project


def test_scanner_output_flows_into_a_plan(tmp_path: Path) -> None:
    """The whole path: a real scan of a real directory, into a real plan."""
    project = write_system(tmp_path)

    report = ReadinessScanner(project).scan_readiness().to_dict()
    findings = findings_from_readiness(report)
    plan = RemediationPlanner.from_catalog(default_catalog_path("eu-ai-act-v1")).plan(
        findings, system_id=report["system_id"], system_name=report["system_name"]
    )

    assert findings, "a bare system.yaml must produce findings"
    assert plan.items, "those findings must produce actionable work"
    assert not plan.unguided, f"uncovered findings: {[f.finding_id for f in plan.unguided]}"
    assert plan.blocking_items, "a system with no instrumentation has blocking gaps"


def test_cli_writes_a_plan_and_gates_on_blocking_items(tmp_path: Path) -> None:
    project = write_system(tmp_path)
    report = ReadinessScanner(project).scan_readiness().to_dict()
    readiness = tmp_path / "readiness.json"
    readiness.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "plan" / "remediation.md"

    exit_code = main(
        [
            "--readiness",
            str(readiness),
            "--output",
            str(out),
            "--fail-on-blocking",
        ]
    )

    assert exit_code == 1, "blocking items must fail the gate"
    assert out.exists()
    assert "Remediation plan" in out.read_text(encoding="utf-8")


def test_cli_requires_at_least_one_input() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_cli_reports_a_missing_catalog_rather_than_an_empty_plan(tmp_path: Path) -> None:
    readiness = tmp_path / "r.json"
    readiness.write_text(json.dumps({"checks": []}), encoding="utf-8")

    assert main(["--readiness", str(readiness), "--framework", "does-not-exist"]) == 2


def test_json_output_round_trips(tmp_path: Path) -> None:
    project = write_system(tmp_path)
    report = ReadinessScanner(project).scan_readiness().to_dict()
    readiness = tmp_path / "readiness.json"
    readiness.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "plan.json"

    main(["--readiness", str(readiness), "--format", "json", "--output", str(out)])
    parsed = json.loads(out.read_text(encoding="utf-8"))

    assert parsed["framework"] == "eu-ai-act-v1"
    assert parsed["disclaimer"] == DISCLAIMER
    assert parsed["items"], "a plan with no items would be a silent pass"
    assert all(item["triggered_by"] for item in parsed["items"])
