"""The audit package now carries what actually ran, not only what is configured.

`ReadinessScanner` reads a project directory: it answers "is this system set up
correctly". Nothing in the package asked a trace store what happened, so a
system with a live trace store produced an audit package containing none of its
evidence — the configured half and the observed half never met.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from compliance.src import audit_generator
from compliance.src.audit_generator import generate_audit_package

CONTROLS = """framework: demo-framework
version: "1.0"
articles:
  - id: art-1
    title: Logging
    controls:
      - id: art-1.1
        title: Automatic recording of events
        evidence_types: [logs]
        evidence_query:
          event_types: [AGENT_START, TOOL_CALL]
        mandatory: true
        priority: critical
      - id: art-1.2
        title: Human oversight
        evidence_types: [approvals]
        evidence_query:
          event_types: [HUMAN_ESCALATION]
        mandatory: true
        priority: critical
      - id: art-1.3
        title: Documented purpose
        evidence_types: [purpose_statement]
        mandatory: true
        priority: high
"""


def _system(trace_store_url: str | None) -> str:
    integration = "{agent_id: demo-agent, guardian_policy: default"
    if trace_store_url:
        integration += f', trace_store_url: "{trace_store_url}"'
    integration += "}"
    return f"""system:
  id: demo
  name: Demo
  provider_role: deployer
  risk_class: limited-risk
  approved_use_cases: [demo]
  owner: {{business: owner, technical: maintainer}}
  data_classes: [public_data]
  human_oversight: {{type: human-in-command, approval_points: [release]}}
  integration: {integration}
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


def _project(tmp_path: Path, trace_store_url: str | None) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "system.yaml").write_text(_system(trace_store_url), encoding="utf-8")
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    (project / "tests").mkdir()
    return project


def _framework(tmp_path: Path) -> Path:
    path = tmp_path / "demo-framework.yaml"
    path.write_text(CONTROLS, encoding="utf-8")
    return path


def _event(event_type: str) -> dict[str, Any]:
    return {
        "trace_id": "11111111-1111-4111-8111-111111111111",
        "agent_id": "demo-agent",
        "session_id": "S1",
        "timestamp": "2026-08-08T10:00:00Z",
        "event_type": event_type,
        "cynefin_domain": "DISORDER",
        "payload": {},
        "metrics": {},
    }


@pytest.fixture
def fake_trace_store(monkeypatch: pytest.MonkeyPatch):
    """Stand in for a trace store so the test needs no network."""

    def _install(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        def fake_query(self, **kwargs):
            calls.append(kwargs)
            event_type = kwargs.get("event_type")
            if event_type:
                return [e for e in events if e["event_type"] == event_type]
            return events

        monkeypatch.setattr(
            audit_generator.EvidenceLinker, "query_trace_store", fake_query, raising=True
        )
        return calls

    return _install


def test_audit_package_carries_runtime_evidence(tmp_path: Path, fake_trace_store) -> None:
    calls = fake_trace_store([_event("AGENT_START"), _event("TOOL_CALL")])
    project = _project(tmp_path, "http://127.0.0.1:8089")

    package = generate_audit_package([project], framework_paths=[_framework(tmp_path)])
    runtime = package["systems"][0]["runtime_evidence"]

    assert runtime["events_examined"] == 2
    # Scoped to this system's agent, so one trace store serving several systems
    # does not credit one system with another's evidence.
    assert calls[0]["agent_id"] == "demo-agent"

    by_id = {c["control_id"]: c for c in runtime["controls"]}
    # Outcomes, not a boolean: QueryOutcome keeps "we cannot tell" apart from
    # "we checked and it failed", and the audit package must not merge them.
    assert by_id["art-1.1"]["outcome"] == "satisfied"
    assert by_id["art-1.2"]["outcome"] in {"unsatisfied", "indeterminate"}
    # A control evidenced by documents rather than events is absent entirely.
    # Listing it as unsatisfied would turn "not this kind of evidence" into
    # "missing evidence", which is a finding it has not earned.
    assert "art-1.3" not in by_id
    assert runtime["controls_evidenced"] == 1
    assert runtime["controls_queried"] == 2


def test_says_when_no_events_came_back(tmp_path: Path, fake_trace_store) -> None:
    fake_trace_store([])
    project = _project(tmp_path, "http://127.0.0.1:8089")

    package = generate_audit_package([project], framework_paths=[_framework(tmp_path)])
    runtime = package["systems"][0]["runtime_evidence"]

    # EvidenceLinker catches every HTTP error and returns [], so an empty result
    # cannot distinguish "recorded nothing" from "could not reach the store".
    # An audit package must not let a reachability failure read as a finding.
    assert runtime["events_examined"] == 0
    assert "unreachable" in runtime["events_note"]


def test_omits_the_section_when_no_trace_store_is_declared(tmp_path: Path) -> None:
    project = _project(tmp_path, None)

    package = generate_audit_package([project], framework_paths=[_framework(tmp_path)])

    # None, not an empty result: a system with no trace store should say nothing
    # about runtime evidence rather than imply there was none to find.
    assert package["systems"][0]["runtime_evidence"] is None


def test_a_broken_framework_does_not_fail_the_audit(tmp_path: Path, fake_trace_store) -> None:
    fake_trace_store([_event("AGENT_START")])
    project = _project(tmp_path, "http://127.0.0.1:8089")
    broken = tmp_path / "broken.yaml"
    broken.write_text("framework: broken\nversion: '1'\narticles: not-a-list\n", encoding="utf-8")

    package = generate_audit_package([project], framework_paths=[broken])
    runtime = package["systems"][0]["runtime_evidence"]

    # Reported, not raised. One unparseable framework must not deny an auditor
    # the rest of the package.
    assert any("error" in item for item in runtime["controls"])


def test_markdown_renders_the_runtime_section(tmp_path: Path, fake_trace_store) -> None:
    fake_trace_store([_event("AGENT_START"), _event("TOOL_CALL")])
    project = _project(tmp_path, "http://127.0.0.1:8089")
    out = tmp_path / "audit"

    generate_audit_package([project], framework_paths=[_framework(tmp_path)], output_dir=out)
    markdown = (out / "audit-package.md").read_text(encoding="utf-8")
    package = json.loads((out / "audit-package.json").read_text(encoding="utf-8"))

    assert "### Runtime Evidence" in markdown
    assert "art-1.1" in markdown
    assert package["systems"][0]["runtime_evidence"]["events_examined"] == 2
