from __future__ import annotations

from pathlib import Path

from compliance.src.audit_generator import generate_audit_package
from compliance.src.report_generator import generate_dashboard_report

SYSTEM = """system:
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
"""


def test_generators_write_dashboard_and_audit_artifacts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "system.yaml").write_text(SYSTEM, encoding="utf-8")
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    (project / "tests").mkdir()
    dashboard = tmp_path / "dashboard.json"
    audit_dir = tmp_path / "audit"

    dashboard_report = generate_dashboard_report([project], dashboard)
    audit_report = generate_audit_package([project], output_dir=audit_dir)

    assert dashboard.exists()
    assert dashboard_report["overall_summary"]["overall_readiness_percent"] == 100.0
    assert (audit_dir / "audit-package.json").exists()
    assert (audit_dir / "audit-package.md").exists()
    assert audit_report["overall_summary"]["total_systems"] == 1
