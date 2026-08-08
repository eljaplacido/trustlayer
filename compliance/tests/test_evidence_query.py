"""Tests for evidence query v2 and assurance tiers (ADR-018).

The cases that matter most here are the ones about *not over-claiming*:
coverage over an empty population, a pass that cannot reach VERIFIED, and a
broken integrity chain pulling a control back down. A query engine that is
merely correct on the happy path will still produce a compliance report that
lies.
"""

from __future__ import annotations

from typing import Any

import pytest
from compliance.src.evidence_query import (
    AssuranceReport,
    AssuranceTier,
    EvidenceQuery,
    IntegrityStatus,
    QueryOutcome,
    assign_tier,
    event_time,
    parse_duration,
    tier_at_least,
)


def event(
    trace_id: str,
    event_type: str,
    *,
    session: str = "s1",
    timestamp: str = "2026-08-07T10:00:00+00:00",
    **payload: Any,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "agent_id": "a",
        "session_id": session,
        "timestamp": timestamp,
        "event_type": event_type,
        "cynefin_domain": "CLEAR",
        "payload": payload,
        "metrics": {},
    }


# --- durations -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("5s", 5), ("10m", 600), ("24h", 86400), ("90d", 7776000), ("30", 30), (45, 45)],
)
def test_parse_duration(raw: str | int, seconds: int) -> None:
    assert parse_duration(raw).total_seconds() == seconds


@pytest.mark.parametrize("raw", ["", "abc", "5x", "  "])
def test_parse_duration_rejects_nonsense(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(raw)


def test_event_time_returns_none_rather_than_raising() -> None:
    """One malformed event must not fail an entire query."""
    assert event_time({"timestamp": "not-a-time"}) is None
    assert event_time({}) is None
    assert event_time({"timestamp": "2026-08-07T10:00:00Z"}) is not None


# --- v1 compatibility ------------------------------------------------------


def test_v1_presence_query_keeps_its_meaning() -> None:
    query = EvidenceQuery.parse({"event_types": ["TOOL_CALL"], "min_count": 2})
    events = [event("1", "TOOL_CALL"), event("2", "TOOL_CALL"), event("3", "LLM_CALL")]

    result = query.evaluate(events)

    assert result.outcome is QueryOutcome.SATISFIED
    assert result.satisfied_count == 2
    assert not query.is_v2


def test_v1_presence_query_reports_the_shortfall() -> None:
    query = EvidenceQuery.parse({"event_types": ["TOOL_CALL"], "min_count": 5})

    result = query.evaluate([event("1", "TOOL_CALL")])

    assert result.outcome is QueryOutcome.UNSATISFIED
    assert "need at least 5" in (result.reason or "")


def test_payload_filters_lowers_to_where() -> None:
    """One code path, so a v1 catalog cannot drift from a v2 one."""
    query = EvidenceQuery.parse(
        {"event_types": ["POLICY_CHECK"], "payload_filters": {"result": "PASS"}}
    )

    assert query.where == {"result": "PASS"}
    result = query.evaluate(
        [event("1", "POLICY_CHECK", result="PASS"), event("2", "POLICY_CHECK", result="FAIL")]
    )
    assert result.satisfied_count == 1


def test_where_overrides_payload_filters_on_the_same_key() -> None:
    query = EvidenceQuery.parse(
        {"payload_filters": {"result": "PASS"}, "where": {"result": {"$in": ["PASS", "ESCALATE"]}}}
    )

    assert query.where["result"] == {"$in": ["PASS", "ESCALATE"]}


# --- absence ---------------------------------------------------------------


def test_absence_is_satisfied_when_nothing_matches() -> None:
    query = EvidenceQuery.parse(
        {"absence": {"event_type": "TOOL_CALL", "where": {"tool_name": {"$prefix": "restricted."}}}}
    )

    result = query.evaluate([event("1", "TOOL_CALL", tool_name="safe.read")])

    assert result.outcome is QueryOutcome.SATISFIED


def test_absence_fails_and_cites_the_offending_events() -> None:
    query = EvidenceQuery.parse(
        {"absence": {"event_type": "TOOL_CALL", "where": {"tool_name": {"$prefix": "restricted."}}}}
    )

    result = query.evaluate(
        [
            event("1", "TOOL_CALL", tool_name="safe.read"),
            event("2", "TOOL_CALL", tool_name="restricted.delete"),
        ]
    )

    assert result.outcome is QueryOutcome.UNSATISFIED
    assert result.violations[0].trace_ids == ("2",)


def test_absence_over_an_empty_stream_is_satisfied() -> None:
    """ "No events at all" genuinely satisfies "none of this kind happened".

    Over-claiming from an empty log is prevented at the tier level instead —
    see `test_a_pass_over_an_empty_population_cannot_be_evidenced`.
    """
    query = EvidenceQuery.parse({"absence": {"event_type": "TOOL_CALL"}})

    assert query.evaluate([]).outcome is QueryOutcome.SATISFIED


# --- coverage --------------------------------------------------------------


def test_coverage_over_an_empty_population_is_indeterminate_not_a_pass() -> None:
    """The most dangerous thing this engine could do is report 100% here.

    A system that emitted no risky calls at all would otherwise look perfectly
    governed.
    """
    query = EvidenceQuery.parse(
        {
            "coverage": {
                "of": {"event_type": "TOOL_CALL", "where": {"trust_tier": "privileged"}},
                "satisfied_by": {"event_type": "TOOL_CALL"},
            }
        }
    )

    result = query.evaluate([event("1", "LLM_CALL")])

    assert result.outcome is QueryOutcome.INDETERMINATE
    assert result.coverage_ratio is None
    assert "not a pass" in (result.reason or "")


def test_coverage_computes_the_ratio_an_auditor_asks_for() -> None:
    query = EvidenceQuery.parse(
        {
            "coverage": {
                "of": {"event_type": "TOOL_CALL"},
                "satisfied_by": {"event_type": "TOOL_CALL", "where": {"gated": True}},
                "min_ratio": 0.99,
            }
        }
    )
    events = [
        event("1", "TOOL_CALL", gated=True),
        event("2", "TOOL_CALL", gated=True),
        event("3", "TOOL_CALL", gated=False),
    ]

    result = query.evaluate(events)

    assert result.population == 3
    assert result.satisfied_count == 2
    assert result.coverage_ratio == pytest.approx(2 / 3)
    assert result.outcome is QueryOutcome.UNSATISFIED
    assert result.violations[0].trace_ids == ("3",)


def test_full_coverage_satisfies() -> None:
    query = EvidenceQuery.parse(
        {
            "coverage": {
                "of": {"event_type": "TOOL_CALL"},
                "satisfied_by": {"event_type": "TOOL_CALL", "where": {"gated": True}},
                "min_ratio": 1.0,
            }
        }
    )

    result = query.evaluate([event("1", "TOOL_CALL", gated=True)])

    assert result.outcome is QueryOutcome.SATISFIED
    assert result.coverage_ratio == 1.0


# --- sequence --------------------------------------------------------------


def test_sequence_requires_a_preceding_event() -> None:
    """Art. 15's real question: was *every* risky action gated?"""
    query = EvidenceQuery.parse(
        {
            "sequence": [
                {
                    "match": {
                        "event_type": "TOOL_CALL",
                        "where": {"tool_name": "payments.transfer"},
                    },
                    "requires_preceding": {
                        "match": {"event_type": "POLICY_CHECK", "where": {"result": "PASS"}},
                        "within": "5s",
                        "same_session": True,
                    },
                }
            ]
        }
    )
    events = [
        event("1", "POLICY_CHECK", timestamp="2026-08-07T10:00:00+00:00", result="PASS"),
        event(
            "2", "TOOL_CALL", timestamp="2026-08-07T10:00:01+00:00", tool_name="payments.transfer"
        ),
    ]

    assert query.evaluate(events).outcome is QueryOutcome.SATISFIED


def test_sequence_fails_when_the_gate_is_missing() -> None:
    query = EvidenceQuery.parse(
        {
            "sequence": [
                {
                    "match": {"event_type": "TOOL_CALL"},
                    "requires_preceding": {"match": {"event_type": "POLICY_CHECK"}},
                }
            ]
        }
    )

    result = query.evaluate([event("2", "TOOL_CALL")])

    assert result.outcome is QueryOutcome.UNSATISFIED
    assert result.violations[0].trace_ids == ("2",)


def test_sequence_rejects_a_predecessor_outside_the_window() -> None:
    query = EvidenceQuery.parse(
        {
            "sequence": [
                {
                    "match": {"event_type": "TOOL_CALL"},
                    "requires_preceding": {
                        "match": {"event_type": "POLICY_CHECK"},
                        "within": "5s",
                    },
                }
            ]
        }
    )
    events = [
        event("1", "POLICY_CHECK", timestamp="2026-08-07T10:00:00+00:00"),
        event("2", "TOOL_CALL", timestamp="2026-08-07T10:01:00+00:00"),
    ]

    assert query.evaluate(events).outcome is QueryOutcome.UNSATISFIED


def test_sequence_rejects_a_predecessor_in_another_session() -> None:
    query = EvidenceQuery.parse(
        {
            "sequence": [
                {
                    "match": {"event_type": "TOOL_CALL"},
                    "requires_preceding": {
                        "match": {"event_type": "POLICY_CHECK"},
                        "same_session": True,
                    },
                }
            ]
        }
    )
    events = [
        event("1", "POLICY_CHECK", session="other", timestamp="2026-08-07T10:00:00+00:00"),
        event("2", "TOOL_CALL", session="s1", timestamp="2026-08-07T10:00:01+00:00"),
    ]

    assert query.evaluate(events).outcome is QueryOutcome.UNSATISFIED


def test_a_later_event_does_not_count_as_a_predecessor() -> None:
    """Otherwise a check performed *after* the action would satisfy the gate."""
    query = EvidenceQuery.parse(
        {
            "sequence": [
                {
                    "match": {"event_type": "TOOL_CALL"},
                    "requires_preceding": {"match": {"event_type": "POLICY_CHECK"}},
                }
            ]
        }
    )
    events = [
        event("2", "TOOL_CALL", timestamp="2026-08-07T10:00:00+00:00"),
        event("1", "POLICY_CHECK", timestamp="2026-08-07T10:00:05+00:00"),
    ]

    assert query.evaluate(events).outcome is QueryOutcome.UNSATISFIED


def test_an_untimed_event_cannot_satisfy_a_temporal_requirement() -> None:
    """A missing timestamp must not be a free pass on an ordering control."""
    query = EvidenceQuery.parse(
        {
            "sequence": [
                {
                    "match": {"event_type": "TOOL_CALL"},
                    "requires_preceding": {"match": {"event_type": "POLICY_CHECK"}},
                }
            ]
        }
    )
    gate = event("1", "POLICY_CHECK")
    del gate["timestamp"]

    assert query.evaluate([gate, event("2", "TOOL_CALL")]).outcome is QueryOutcome.UNSATISFIED


def test_sequence_with_no_targets_is_indeterminate() -> None:
    query = EvidenceQuery.parse(
        {"sequence": [{"match": {"event_type": "TOOL_CALL"}, "requires_preceding": {}}]}
    )

    assert query.evaluate([event("1", "LLM_CALL")]).outcome is QueryOutcome.INDETERMINATE


# --- resolution ------------------------------------------------------------


def test_resolution_requires_escalations_to_close() -> None:
    """An escalation nobody acted on is worse evidence than no escalation."""
    query = EvidenceQuery.parse(
        {
            "resolution": {
                "opens_with": {"event_type": "HUMAN_ESCALATION"},
                "closes_with": {"event_type": "HUMAN_DECISION"},
                "within": "24h",
            }
        }
    )
    events = [
        event("1", "HUMAN_ESCALATION", timestamp="2026-08-07T10:00:00+00:00"),
        event("2", "HUMAN_DECISION", timestamp="2026-08-07T12:00:00+00:00"),
    ]

    assert query.evaluate(events).outcome is QueryOutcome.SATISFIED


def test_resolution_fails_on_an_unclosed_escalation() -> None:
    query = EvidenceQuery.parse(
        {
            "resolution": {
                "opens_with": {"event_type": "HUMAN_ESCALATION"},
                "closes_with": {"event_type": "HUMAN_DECISION"},
            }
        }
    )

    result = query.evaluate([event("1", "HUMAN_ESCALATION")])

    assert result.outcome is QueryOutcome.UNSATISFIED
    assert result.violations[0].trace_ids == ("1",)


def test_resolution_rejects_a_decision_outside_the_deadline() -> None:
    query = EvidenceQuery.parse(
        {
            "resolution": {
                "opens_with": {"event_type": "HUMAN_ESCALATION"},
                "closes_with": {"event_type": "HUMAN_DECISION"},
                "within": "1h",
            }
        }
    )
    events = [
        event("1", "HUMAN_ESCALATION", timestamp="2026-08-07T10:00:00+00:00"),
        event("2", "HUMAN_DECISION", timestamp="2026-08-08T10:00:00+00:00"),
    ]

    assert query.evaluate(events).outcome is QueryOutcome.UNSATISFIED


def test_resolution_with_no_escalations_is_indeterminate() -> None:
    query = EvidenceQuery.parse(
        {"resolution": {"opens_with": {"event_type": "HUMAN_ESCALATION"}, "closes_with": {}}}
    )

    assert query.evaluate([event("1", "TOOL_CALL")]).outcome is QueryOutcome.INDETERMINATE


# --- validation ------------------------------------------------------------


def test_query_validation_surfaces_predicate_problems() -> None:
    query = EvidenceQuery.parse({"where": {"a": {"$nope": 1}}})

    problems = query.validate()

    assert len(problems) == 1
    assert "unknown operator" in problems[0]


def test_query_validation_rejects_a_ratio_outside_zero_to_one() -> None:
    query = EvidenceQuery.parse({"coverage": {"of": {"event_type": "TOOL_CALL"}, "min_ratio": 1.5}})

    assert any("min_ratio" in p for p in query.validate())


def test_query_validation_rejects_a_malformed_window() -> None:
    query = EvidenceQuery.parse(
        {"sequence": [{"match": {}, "requires_preceding": {"match": {}, "within": "banana"}}]}
    )

    assert any("banana" in p for p in query.validate())


def test_a_clean_v2_query_validates() -> None:
    query = EvidenceQuery.parse(
        {
            "coverage": {
                "of": {"event_type": "TOOL_CALL", "where": {"tool_name": {"$prefix": "pay."}}},
                "satisfied_by": {"event_type": "TOOL_CALL"},
                "min_ratio": 0.99,
            }
        }
    )

    assert query.validate() == []
    assert query.is_v2


# --- assurance tiers -------------------------------------------------------


def satisfied_result(population: int = 5) -> Any:
    return EvidenceQuery.parse({"event_types": ["TOOL_CALL"]}).evaluate(
        [event(str(i), "TOOL_CALL") for i in range(population)]
    )


def test_a_failing_query_never_rises_above_declared() -> None:
    """Whatever the system asserts about itself."""
    result = EvidenceQuery.parse({"event_types": ["TOOL_CALL"], "min_count": 99}).evaluate(
        [event("1", "TOOL_CALL")]
    )

    assert (
        assign_tier(result, declared=True, integrity=IntegrityStatus.VERIFIED)
        is AssuranceTier.DECLARED
    )


def test_an_undeclared_failing_control_is_unknown_not_declared() -> None:
    result = EvidenceQuery.parse({"event_types": ["X"], "min_count": 1}).evaluate([])

    assert (
        assign_tier(result, declared=False, integrity=IntegrityStatus.VERIFIED)
        is AssuranceTier.UNKNOWN
    )


def test_a_passing_query_is_evidenced() -> None:
    assert (
        assign_tier(satisfied_result(), declared=True, integrity=IntegrityStatus.UNCHAINED)
        is AssuranceTier.EVIDENCED
    )


def test_a_pass_over_an_empty_population_cannot_be_evidenced() -> None:
    """A pass over zero events is not evidence of anything."""
    result = EvidenceQuery.parse({"event_types": ["TOOL_CALL"], "min_count": 0}).evaluate([])

    assert result.outcome is QueryOutcome.SATISFIED
    assert (
        assign_tier(result, declared=True, integrity=IntegrityStatus.VERIFIED)
        is AssuranceTier.DECLARED
    )


def test_verified_requires_integrity_and_independent_confirmation() -> None:
    """Without independent confirmation, VERIFIED would mean "the system said
    so and the log was not edited" — which is not independent of the party
    being assessed."""
    result = satisfied_result()

    assert (
        assign_tier(result, declared=True, integrity=IntegrityStatus.VERIFIED)
        is AssuranceTier.EVIDENCED
    )
    assert (
        assign_tier(
            result,
            declared=True,
            integrity=IntegrityStatus.VERIFIED,
            independently_confirmed=True,
        )
        is AssuranceTier.VERIFIED
    )


def test_an_unchained_log_cannot_reach_verified() -> None:
    assert (
        assign_tier(
            satisfied_result(),
            declared=True,
            integrity=IntegrityStatus.UNCHAINED,
            independently_confirmed=True,
        )
        is AssuranceTier.EVIDENCED
    )


def test_a_failed_integrity_chain_pulls_the_control_back_down() -> None:
    """A broken chain does not merely fail to strengthen the claim — it
    undermines the evidence the claim rests on."""
    assert (
        assign_tier(
            satisfied_result(),
            declared=True,
            integrity=IntegrityStatus.FAILED,
            independently_confirmed=True,
        )
        is AssuranceTier.DECLARED
    )


def test_indeterminate_does_not_become_evidenced() -> None:
    result = EvidenceQuery.parse(
        {"coverage": {"of": {"event_type": "NOTHING"}, "satisfied_by": {}}}
    ).evaluate([])

    assert result.outcome is QueryOutcome.INDETERMINATE
    assert (
        assign_tier(result, declared=True, integrity=IntegrityStatus.VERIFIED)
        is AssuranceTier.DECLARED
    )


@pytest.mark.parametrize(
    ("tier", "floor", "expected"),
    [
        (AssuranceTier.VERIFIED, AssuranceTier.EVIDENCED, True),
        (AssuranceTier.EVIDENCED, AssuranceTier.EVIDENCED, True),
        (AssuranceTier.DECLARED, AssuranceTier.EVIDENCED, False),
        (AssuranceTier.UNKNOWN, AssuranceTier.DECLARED, False),
    ],
)
def test_tier_ordering(tier: AssuranceTier, floor: AssuranceTier, expected: bool) -> None:
    assert tier_at_least(tier, floor) is expected


# --- the report ------------------------------------------------------------


def test_assurance_report_counts_per_tier() -> None:
    report = AssuranceReport()
    for tier in (
        AssuranceTier.VERIFIED,
        AssuranceTier.EVIDENCED,
        AssuranceTier.EVIDENCED,
        AssuranceTier.DECLARED,
    ):
        report.add(tier)

    assert report.total == 4
    assert report.evidenced == 2
    assert report.count_at_least(AssuranceTier.EVIDENCED) == 3


def test_assurance_report_has_no_blended_score() -> None:
    """Blending is how a field-presence check becomes a "92% compliant"
    headline. The absence of that key is the feature."""
    payload = AssuranceReport(declared=5, evidenced=1).to_dict()

    for forbidden in ("readiness_score_percent", "satisfaction_rate_percent", "score"):
        assert forbidden not in payload
    assert "never blended" in payload["note"]


def test_an_unimplemented_scope_is_rejected_rather_than_ignored() -> None:
    """A query silently evaluated over a wider set than asked for answers a
    question nobody posed, and the author cannot tell."""
    query = EvidenceQuery.parse({"scope": "session", "event_types": ["TOOL_CALL"]})

    problems = query.validate()

    assert any("scope" in p and "not implemented" in p for p in problems)


def test_an_unimplemented_window_is_rejected() -> None:
    query = EvidenceQuery.parse({"window": "90d", "event_types": ["TOOL_CALL"]})

    assert any("window" in p for p in query.validate())


def test_the_default_scope_is_accepted() -> None:
    assert EvidenceQuery.parse({"scope": "system"}).validate() == []
    assert EvidenceQuery.parse({}).validate() == []
