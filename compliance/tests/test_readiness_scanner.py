from __future__ import annotations

from pathlib import Path

import pytest
from compliance.src.readiness_scanner import ReadinessScanner


def write_system(project: Path, body: str) -> None:
    (project / "system.yaml").write_text(body, encoding="utf-8")


def test_scan_reports_all_readiness_checks_for_valid_system(tmp_path: Path) -> None:
    write_system(
        tmp_path,
        """system:
  id: demo
  name: Demo
  provider_role: deployer
  risk_class: limited-risk
  approved_use_cases: [demo]
  owner: {business: owner, technical: maintainer}
  data_classes: [public_data]
  human_oversight: {type: human-in-command, approval_points: [release]}
  integration: {agent_id: demo-agent, guardian_policy: default}
""",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    report = ReadinessScanner(tmp_path).scan_readiness()

    # 10 existing checks + 3 Art. 50 SKIPs (no article_50 block defined)
    assert report.summary["total_checks"] == 13
    assert report.summary["skipped"] == 3
    # Readiness = PASS / (PASS + FAIL + GAP), SKIPs excluded from denominator
    assert report.summary["readiness_score_percent"] == 100.0


def test_scan_rejects_registry_missing_schema_requirements(tmp_path: Path) -> None:
    write_system(tmp_path, "system: {id: demo}\n")

    with pytest.raises(Exception, match="name"):
        ReadinessScanner(tmp_path).scan_readiness()


def test_scan_reports_missing_registry_as_critical_failure(tmp_path: Path) -> None:
    report = ReadinessScanner(tmp_path).scan_readiness()

    assert report.summary["failed"] == 1
    assert report.checks[0].check_id == "system-registry"


def test_scan_reports_art50_pass_when_article_50_block_present(tmp_path: Path) -> None:
    write_system(
        tmp_path,
        """system:
  id: demo
  name: Demo
  provider_role: deployer
  risk_class: limited-risk
  approved_use_cases: [demo]
  owner: {business: owner, technical: maintainer}
  data_classes: [public_data]
  human_oversight: {type: human-in-command, approval_points: [release]}
  integration: {agent_id: demo-agent, guardian_policy: default}
  article_50:
    disclosure_config:
      disclose_ai_interaction: true
      disclose_biometric_classification: true
      disclose_emotion_recognition: true
    marking_config:
      mark_generated_content: true
      generates_synthetic_content: true
    biometric_handling:
      consent_mechanism: "Explicit opt-in"
""",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    report = ReadinessScanner(tmp_path).scan_readiness()

    # 10 existing + 3 Art. 50 PASS = 13 checks, no skips
    assert report.summary["total_checks"] == 13
    assert report.summary["skipped"] == 0
    assert report.summary["passed"] == 13
    assert report.summary["readiness_score_percent"] == 100.0

    # Verify Art. 50 check statuses
    art50_checks = [c for c in report.checks if c.check_id.startswith("art-50")]
    assert len(art50_checks) == 3
    for c in art50_checks:
        assert c.status == "PASS"


def test_scan_reports_art50_gap_for_missing_disclosure(tmp_path: Path) -> None:
    write_system(
        tmp_path,
        """system:
  id: demo
  name: Demo
  provider_role: deployer
  risk_class: limited-risk
  approved_use_cases: [demo]
  owner: {business: owner, technical: maintainer}
  data_classes: [public_data]
  human_oversight: {type: human-in-command, approval_points: [release]}
  integration: {agent_id: demo-agent, guardian_policy: default}
  article_50:
    marking_config:
      mark_generated_content: true
      generates_synthetic_content: true
    biometric_handling:
      consent_mechanism: "Explicit opt-in"
""",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    report = ReadinessScanner(tmp_path).scan_readiness()

    # 10 existing + 3 Art. 50 (art-50.1 GAP + art-50.2 PASS + art-50.3 PASS) = 13
    assert report.summary["total_checks"] == 13
    assert report.summary["gaps"] == 1

    art50_1 = next(c for c in report.checks if c.check_id == "art-50.1")
    assert art50_1.status == "GAP"
    assert "disclosure" in art50_1.details.lower()
