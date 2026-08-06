from __future__ import annotations

import re
from pathlib import Path

import pytest
from compliance.src import readiness_scanner
from compliance.src.readiness_scanner import (
    PASS_ONLY_CHECK_IDS,
    REMEDIABLE_CHECK_IDS,
    ReadinessScanner,
)


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


def test_scan_treats_declared_non_applicability_as_a_recorded_determination(
    tmp_path: Path,
) -> None:
    """`article_50.enabled: false` is an answer, not a gap.

    Reporting it as a gap conflates "the obligation applies and is unmet" with
    "the obligation was considered and found inapplicable", producing a
    permanent false finding. A tool that is always red about something correct
    trains people to ignore it.

    Found by pointing the scanner at TrustLayer's own `system.yaml`
    (design principle P8 — dogfood).
    """
    write_system(
        tmp_path,
        """system:
  id: demo
  name: Demo
  provider_role: provider
  risk_class: minimal-risk
  approved_use_cases: [demo]
  owner: {business: owner, technical: maintainer}
  data_classes: [public_data]
  human_oversight: {type: human-in-command, approval_points: [release]}
  integration: {agent_id: demo-agent, guardian_policy: default}
  article_50:
    enabled: false
    disclosure_config:
      disclose_ai_interaction: false
""",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    report = ReadinessScanner(tmp_path).scan_readiness()
    ids = {c.check_id for c in report.checks}

    assert "art-50.applicability" in ids
    assert not {"art-50.1", "art-50.2", "art-50.3"} & ids, (
        "the per-obligation checks must not also run once Art. 50 is declared "
        "inapplicable — they would contradict the determination"
    )

    applicability = next(c for c in report.checks if c.check_id == "art-50.applicability")
    assert applicability.status == "PASS"
    # The determination must stay visible rather than becoming a silent green.
    assert "determination" in applicability.details.lower()
    assert "not a verified fact" in applicability.details.lower()


def test_declared_non_applicability_still_requires_the_flag_to_be_explicit(
    tmp_path: Path,
) -> None:
    """Omitting `enabled` is not the same as setting it to false.

    A missing field means nobody decided; only an explicit `false` records a
    determination. Treating absence as a determination would let a system opt
    out of Art. 50 by forgetting about it.
    """
    write_system(
        tmp_path,
        """system:
  id: demo
  name: Demo
  provider_role: provider
  risk_class: minimal-risk
  approved_use_cases: [demo]
  owner: {business: owner, technical: maintainer}
  data_classes: [public_data]
  human_oversight: {type: human-in-command, approval_points: [release]}
  integration: {agent_id: demo-agent, guardian_policy: default}
  article_50:
    disclosure_config:
      disclose_ai_interaction: false
""",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    report = ReadinessScanner(tmp_path).scan_readiness()
    ids = {c.check_id for c in report.checks}

    assert "art-50.applicability" not in ids
    assert next(c for c in report.checks if c.check_id == "art-50.1").status == "GAP"


def test_declared_check_ids_stay_in_sync_with_the_source() -> None:
    """`REMEDIABLE_CHECK_IDS` is the contract the remediation catalog is tested
    against. If a new check is added here without updating the declaration, the
    completeness test in `test_remediation.py` would keep passing while a real
    gap shipped with no guidance — the silent failure this guard exists to stop.
    """
    source = Path(readiness_scanner.__file__).read_text(encoding="utf-8")
    # Only literals inside `ReadinessCheck(...)` calls, not the declaration
    # block itself, which is a plain set of strings.
    emitted = set(re.findall(r'check_id="([^"]+)"', source))

    declared = REMEDIABLE_CHECK_IDS | PASS_ONLY_CHECK_IDS

    assert emitted - declared == set(), (
        f"checks emitted but not declared: {sorted(emitted - declared)}. "
        "Add them to REMEDIABLE_CHECK_IDS (and write remediation guidance), "
        "or to PASS_ONLY_CHECK_IDS if the check can never fail."
    )
    assert declared - emitted == set(), (
        f"checks declared but never emitted: {sorted(declared - emitted)}"
    )
