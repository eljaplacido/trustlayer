from __future__ import annotations

from pathlib import Path

import pytest
from compliance.src.evidence_linker import EvidenceLinker


def test_evidence_matching_applies_event_type_and_payload_filters() -> None:
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

    assert evidence.satisfied is True
    assert evidence.evidence_count == 2


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
