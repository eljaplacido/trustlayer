"""The evaluator loop: retry once on ungrounded output, then drop."""

from __future__ import annotations

from conftest import IN_WINDOW, OUT_OF_WINDOW, findings_payload, mock_provider_transport

from trustlayer_eval.models import EvaluatorRole
from trustlayer_eval.providers.ollama import OllamaProvider
from trustlayer_eval.roles import InsightAdvisor, indeterminate_controls


def advisor(window: object, payloads: list[str]) -> InsightAdvisor:
    provider = OllamaProvider(transport=mock_provider_transport(payloads))
    return InsightAdvisor(provider, window=window)  # type: ignore[arg-type]


def test_a_grounded_finding_survives(window: object) -> None:
    run = advisor(
        window,
        [
            findings_payload(
                {
                    "claim": "external_llm was called",
                    "cited_trace_ids": [str(IN_WINDOW)],
                    "confidence": "medium",
                    "severity": "low",
                },
                narrative="One external LLM call is visible.",
            )
        ],
    ).run("what happened?")

    assert len(run.findings) == 1
    assert run.ungrounded_rejected == 0
    assert run.narrative == "One external LLM call is visible."


def test_an_ungrounded_finding_is_retried_once_then_kept_if_corrected(
    window: object,
) -> None:
    """The retry carries the rejection reason, and a corrected answer stands."""
    run = advisor(
        window,
        [
            findings_payload(
                {
                    "claim": "fabricated",
                    "cited_trace_ids": [str(OUT_OF_WINDOW)],
                    "confidence": "high",
                    "severity": "high",
                }
            ),
            findings_payload(
                {
                    "claim": "corrected",
                    "cited_trace_ids": [str(IN_WINDOW)],
                    "confidence": "low",
                    "severity": "low",
                }
            ),
        ],
    ).run("what happened?")

    assert [f.claim for f in run.findings] == ["corrected"]
    # The rejected first attempt is still recorded, so "N suppressed" can name
    # what was suppressed.
    assert run.ungrounded_rejected == 1
    assert run.ungrounded[0].claim == "fabricated"


def test_a_second_ungrounded_attempt_is_dropped_not_repaired(window: object) -> None:
    """Two strikes and the finding is gone. There is no third call."""
    payload = findings_payload(
        {
            "claim": "still fabricated",
            "cited_trace_ids": [str(OUT_OF_WINDOW)],
            "confidence": "high",
            "severity": "critical",
        }
    )
    run = advisor(window, [payload, payload]).run("what happened?")

    assert run.findings == ()
    assert run.ungrounded_rejected == 2


def test_unparseable_output_does_not_crash_the_run(window: object) -> None:
    """A run that produced nothing is still a run, and still a record."""
    run = advisor(window, ["not json at all", "still not json"]).run("what happened?")

    assert run.findings == ()
    assert run.role is EvaluatorRole.INSIGHT_ADVISOR


def test_a_json_code_fence_is_tolerated(window: object) -> None:
    """Local models fence their JSON despite instructions not to."""
    fenced = (
        "```json\n"
        + findings_payload(
            {
                "claim": "fenced but valid",
                "cited_trace_ids": [str(IN_WINDOW)],
                "confidence": "low",
                "severity": "info",
            }
        )
        + "\n```"
    )

    run = advisor(window, [fenced]).run("what happened?")

    assert [f.claim for f in run.findings] == ["fenced but valid"]


def test_the_run_records_prompt_provenance(window: object) -> None:
    """A prompt edit must be visible in provenance (ADR-020 §4)."""
    run = advisor(window, [findings_payload()]).run("anything")

    assert len(run.prompt_hash) == 64
    assert run.prompt_version
    assert run.evidence_window.event_count == 2
    assert len(run.evidence_window.result_hash) == 64


def test_the_evidence_window_hash_is_order_independent() -> None:
    """The hash is a property of the set of events, not of the store's ordering.

    Without this, re-running the same query could report the window as moved
    purely because rows came back in a different order.
    """
    from conftest import ALSO_IN_WINDOW, event

    from trustlayer_eval.evidence import window_from_events

    a = window_from_events([event(IN_WINDOW), event(ALSO_IN_WINDOW, seq=2)], query="q")
    b = window_from_events([event(ALSO_IN_WINDOW, seq=2), event(IN_WINDOW)], query="q")

    assert a.result_hash() == b.result_hash()


def test_the_control_judge_sees_only_indeterminate_controls() -> None:
    """Cost is bounded by construction (ADR-020 §4, §5.6).

    This is the assertion that makes a fan-out regression fail CI rather than a
    customer's bill: if the filter ever widens, the expected call count moves.
    """
    controls = [
        {"id": "a", "outcome": "satisfied"},
        {"id": "b", "outcome": "unsatisfied"},
        {"id": "c", "outcome": "indeterminate"},
        {"id": "d", "outcome": "INDETERMINATE"},
        {"id": "e"},
    ]

    eligible = indeterminate_controls(controls)

    assert [c["id"] for c in eligible] == ["c", "d"]
    # One model call per eligible control, and none for the other three.
    assert len(eligible) == 2
