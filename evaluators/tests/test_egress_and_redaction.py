"""Egress policy and redaction (ADR-020 §5)."""

from __future__ import annotations

import pytest
from conftest import IN_WINDOW, event

from trustlayer_eval.egress import EgressPolicy, EgressRefused
from trustlayer_eval.models import Residency
from trustlayer_eval.redaction import Redactor


def test_personal_data_to_a_third_country_is_refused() -> None:
    """Sending a system's traces abroad to assess its compliance posture is
    self-defeating (P7)."""
    policy = EgressPolicy({"data_classes": ["personal_data"]})

    with pytest.raises(EgressRefused) as caught:
        policy.decide(provider="anthropic", residency=Residency.THIRD_COUNTRY)

    decision = caught.value.decision
    assert decision.allowed is False
    # The error must name the data class, the provider, and the override path.
    assert "personal_data" in decision.reason
    assert "anthropic" in decision.reason
    assert "egress_override" in decision.reason


def test_unknown_residency_is_treated_as_third_country() -> None:
    """An unlabelled endpoint is not a safe one."""
    policy = EgressPolicy({"data_classes": ["special_category_data"]})

    with pytest.raises(EgressRefused):
        policy.decide(provider="openai_compat", residency=Residency.UNKNOWN)


def test_local_residency_is_allowed_with_personal_data() -> None:
    policy = EgressPolicy({"data_classes": ["personal_data"]})

    decision = policy.decide(provider="ollama", residency=Residency.LOCAL)

    assert decision.allowed is True


def test_no_restricted_classes_allows_third_country() -> None:
    policy = EgressPolicy({"data_classes": ["telemetry"]})

    assert policy.decide(provider="anthropic", residency=Residency.THIRD_COUNTRY).allowed


def test_an_override_with_a_safeguard_and_approver_is_recorded() -> None:
    """An auditable decision, not a config flag."""
    policy = EgressPolicy(
        {
            "data_classes": ["personal_data"],
            "egress_override": {"safeguard": "SCC-2021/914", "approver": "dpo@example.com"},
        }
    )

    decision = policy.decide(provider="anthropic", residency=Residency.THIRD_COUNTRY)

    assert decision.allowed is True
    assert decision.override_safeguard == "SCC-2021/914"
    assert decision.override_approver == "dpo@example.com"


def test_an_override_missing_its_approver_does_not_count() -> None:
    """A half-filled override would turn the auditable decision back into a
    config flag."""
    policy = EgressPolicy(
        {"data_classes": ["personal_data"], "egress_override": {"safeguard": "SCCs"}}
    )

    with pytest.raises(EgressRefused):
        policy.decide(provider="anthropic", residency=Residency.THIRD_COUNTRY)


def test_an_override_with_a_blank_safeguard_does_not_count() -> None:
    policy = EgressPolicy(
        {
            "data_classes": ["personal_data"],
            "egress_override": {"safeguard": "   ", "approver": "someone"},
        }
    )

    with pytest.raises(EgressRefused):
        policy.decide(provider="anthropic", residency=Residency.THIRD_COUNTRY)


def test_raw_content_is_withheld_by_default() -> None:
    """Opt-in, not opt-out."""
    redactor = Redactor()

    projected = redactor.redact_event(
        event(IN_WINDOW, payload={"tool_name": "llm", "prompt": "secret", "completion": "also"})
    )

    assert projected["payload"] == {"tool_name": "llm"}
    assert redactor.summary().raw_content_included is False


def test_redaction_records_paths_and_counts_but_never_values() -> None:
    """A reviewer must be able to tell a finding was made on partial
    information — without the redacted values leaking into the record."""
    redactor = Redactor()
    redactor.redact_event(event(IN_WINDOW, payload={"prompt": "secret", "tool_name": "t"}))

    summary = redactor.summary()

    assert summary.redacted_paths == ("payload.prompt",)
    assert summary.redacted_count == 1
    assert "secret" not in summary.model_dump_json()


def test_opting_in_includes_raw_content() -> None:
    redactor = Redactor(include_raw_content=True)

    projected = redactor.redact_event(event(IN_WINDOW, payload={"prompt": "visible"}))

    assert projected["payload"]["prompt"] == "visible"
    assert redactor.summary().raw_content_included is True


def test_the_envelope_survives_redaction() -> None:
    """Redaction must not remove the trace_id — a finding could then cite
    nothing."""
    projected = Redactor().redact_event(event(IN_WINDOW))

    assert projected["trace_id"] == str(IN_WINDOW)
    assert projected["event_type"] == "TOOL_CALL"
