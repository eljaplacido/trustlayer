from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from compliance.src.evidence_linker import SCHEMA_VERSION, EvidenceLinker
from compliance.src.evidence_query import AssuranceTier, IntegrityStatus, QueryOutcome


def test_evidence_matching_applies_event_type_and_payload_filters() -> None:
    """A v1 catalog keeps producing the same answer it always did."""
    control = {
        "id": "art-12.1",
        "title": "Audit logging",
        "evidence_query": {
            "event_types": ["POLICY_CHECK"],
            "payload_filters": {"result": "PASS"},
            "min_count": 2,
        },
    }
    events = [
        {"event_type": "POLICY_CHECK", "payload": {"result": "PASS"}},
        {"event_type": "POLICY_CHECK", "payload": {"result": "PASS"}},
        {"event_type": "POLICY_CHECK", "payload": {"result": "FAIL"}},
    ]

    evidence = EvidenceLinker().match_events_to_control(events, control)

    assert evidence.outcome is QueryOutcome.SATISFIED
    assert evidence.satisfied_count == 2
    # Evidence without an integrity check cannot exceed EVIDENCED.
    assert evidence.assurance is AssuranceTier.EVIDENCED


def test_a_declaration_alone_never_reaches_evidenced() -> None:
    """Gap G4 in one assertion: writing it down is not the runtime proving it."""
    control = {"id": "c", "title": "C"}  # no evidence_query

    evidence = EvidenceLinker().match_events_to_control([], control, declared=True)

    assert evidence.assurance is AssuranceTier.DECLARED
    assert "never asked" in (evidence.gap_reason or "")


def test_a_control_nobody_declared_and_nothing_evidenced_is_unknown() -> None:
    evidence = EvidenceLinker().match_events_to_control([], {"id": "c", "title": "C"})

    assert evidence.assurance is AssuranceTier.UNKNOWN


def test_a_malformed_query_does_not_read_as_satisfied() -> None:
    control = {
        "id": "c",
        "title": "C",
        "evidence_query": {"where": {"a": {"$nope": 1}}},
    }

    evidence = EvidenceLinker().match_events_to_control([], control, declared=True)

    assert evidence.assurance is AssuranceTier.UNKNOWN
    assert "unknown operator" in (evidence.gap_reason or "")


# --- role and applicability filtering (G9) ---------------------------------


def test_a_provider_obligation_does_not_bind_a_deployer() -> None:
    control = {"id": "c", "title": "C", "applies_to_roles": ["provider"]}

    evidence = EvidenceLinker().match_events_to_control([], control, provider_role="deployer")

    assert evidence.not_applicable_to_role
    assert "deployer" in (evidence.gap_reason or "")


def test_a_control_binding_every_role_applies_to_a_deployer() -> None:
    control = {"id": "c", "title": "C", "evidence_query": {"min_count": 0}}

    evidence = EvidenceLinker().match_events_to_control([], control, provider_role="deployer")

    assert not evidence.not_applicable_to_role


def test_a_control_not_yet_in_force_is_reported_separately_not_as_a_gap() -> None:
    """Art. 50(2) commences 2026-12-02. Scoring against it today is noise that
    hides the obligations that do apply."""
    control = {"id": "c", "title": "C", "applies_from": "2026-12-02"}

    evidence = EvidenceLinker().match_events_to_control([], control, today=date(2026, 8, 7))

    assert evidence.not_yet_applicable
    assert evidence.applies_from == "2026-12-02"


def test_a_control_already_in_force_is_assessed() -> None:
    control = {"id": "c", "title": "C", "applies_from": "2026-08-02", "evidence_query": {}}

    evidence = EvidenceLinker().match_events_to_control([], control, today=date(2026, 8, 7))

    assert not evidence.not_yet_applicable


def test_a_malformed_commencement_date_does_not_exempt_a_control() -> None:
    control = {"id": "c", "title": "C", "applies_from": "not-a-date", "evidence_query": {}}

    evidence = EvidenceLinker().match_events_to_control([], control, today=date(2026, 8, 7))

    assert not evidence.not_yet_applicable


def test_risk_class_filtering() -> None:
    control = {"id": "c", "title": "C", "risk_classes": ["high-risk"]}

    evidence = EvidenceLinker().match_events_to_control([], control, risk_class="minimal-risk")

    assert evidence.not_applicable_to_role


# --- integrity ------------------------------------------------------------


def test_a_broken_chain_prevents_a_control_from_being_evidenced() -> None:
    control = {"id": "c", "title": "C", "evidence_query": {"event_types": ["TOOL_CALL"]}}
    events = [{"event_type": "TOOL_CALL", "payload": {}}]

    evidence = EvidenceLinker().match_events_to_control(
        events, control, declared=True, integrity=IntegrityStatus.FAILED
    )

    assert evidence.assurance is AssuranceTier.DECLARED


def test_an_unreachable_store_never_reports_verified_integrity() -> None:
    """A store we could not reach must not be able to raise assurance."""
    linker = EvidenceLinker(trace_store_url="http://127.0.0.1:1")

    assert linker.check_integrity("a") is IntegrityStatus.NOT_CHECKED


def test_no_agent_id_means_integrity_was_not_checked() -> None:
    assert EvidenceLinker().check_integrity(None) is IntegrityStatus.NOT_CHECKED


# --- the report -----------------------------------------------------------


def build_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, framework_body: str) -> Any:
    system = tmp_path / "system.yaml"
    framework = tmp_path / "framework.yaml"
    system.write_text(
        """system:
  id: demo
  name: Demo
  provider_role: deployer
  risk_class: limited-risk
  controls: {frameworks: [demo]}
  integration: {agent_id: demo-agent}
""",
        encoding="utf-8",
    )
    framework.write_text(framework_body, encoding="utf-8")
    linker = EvidenceLinker()
    monkeypatch.setattr(linker, "query_trace_store", lambda agent_id: [])
    monkeypatch.setattr(linker, "check_integrity", lambda agent_id: IntegrityStatus.UNCHAINED)
    return linker.generate_compliance_report(system, framework)


def test_report_has_no_blended_satisfaction_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The absence of the number is the feature — see gap G4."""
    report = build_report(
        tmp_path,
        monkeypatch,
        """framework: demo
version: '1'
articles:
  - id: a
    title: A
    controls:
      - id: c
        title: C
        evidence_query: {min_count: 1}
""",
    )
    payload = report.to_dict()

    assert payload["schema_version"] == SCHEMA_VERSION
    assert "satisfaction_rate_percent" not in payload["summary"]
    assert "satisfied" not in payload["controls"][0]
    assert payload["controls"][0]["assurance"] in {t.value for t in AssuranceTier}
    assert "never blended" in payload["assurance"]["note"]


def test_report_excludes_inapplicable_controls_from_the_tier_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = build_report(
        tmp_path,
        monkeypatch,
        """framework: demo
version: '1'
articles:
  - id: a
    title: A
    controls:
      - id: applies
        title: Applies
        evidence_query: {min_count: 1}
      - id: provider-only
        title: Provider only
        applies_to_roles: [provider]
""",
    )

    assert report.summary["total_controls"] == 2
    assert report.summary["applicable_controls"] == 1
    assert report.summary["not_applicable_to_role"] == 1
    assert report.assurance().total == 1


def test_report_uses_full_session_glob_not_prefix_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = tmp_path / "system.yaml"
    framework = tmp_path / "framework.yaml"
    system.write_text(
        """system:
  id: demo
  name: Demo
  provider_role: deployer
  risk_class: limited-risk
  integration: {agent_id: demo-agent, session_id_pattern: 'run-1'}
""",
        encoding="utf-8",
    )
    framework.write_text(
        """framework: demo
version: '1'
articles:
  - id: article
    title: Article
    controls:
      - id: control
        title: Control
        evidence_query: {min_count: 1}
""",
        encoding="utf-8",
    )
    linker = EvidenceLinker()
    monkeypatch.setattr(
        linker,
        "query_trace_store",
        lambda agent_id: [
            {"session_id": "run-1", "event_type": "AGENT_START", "payload": {}},
            {"session_id": "run-1-extra/x", "event_type": "AGENT_START", "payload": {}},
        ],
    )

    report = linker.generate_compliance_report(system, framework)

    assert report.summary["events_analyzed"] == 1


def test_invalid_framework_is_rejected(tmp_path: Path) -> None:
    framework = tmp_path / "framework.yaml"
    framework.write_text("framework: only-name\n", encoding="utf-8")

    with pytest.raises(Exception, match="version"):
        EvidenceLinker().load_control_framework(framework)
