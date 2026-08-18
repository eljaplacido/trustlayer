"""Adversarial fixtures for the grounding validator.

ADR-020 §3 makes these mandatory: fabricated UUIDs, well-formed ids from a
different session, empty citation tuples, duplicated ids, and ids that exist but
do not support the claim. Each one is a way a plausible-looking finding can be
wrong, and the validator is the only thing standing between them and a
compliance artifact.
"""

from __future__ import annotations

from pathlib import Path

import pydantic
import pytest
from conftest import ALSO_IN_WINDOW, IN_WINDOW, OUT_OF_WINDOW, event

from trustlayer_eval.evidence import window_from_events
from trustlayer_eval.grounding import GroundingError, GroundingValidator
from trustlayer_eval.models import Confidence, Finding, Severity, SourceRef


def finding(**overrides: object) -> Finding:
    base: dict[str, object] = {
        "claim": "the guardian blocked an external LLM call",
        "cited_trace_ids": (IN_WINDOW,),
        "confidence": Confidence.MEDIUM,
        "severity": Severity.LOW,
    }
    base.update(overrides)
    return Finding(**base)  # type: ignore[arg-type]


def test_a_finding_with_no_citations_is_not_representable() -> None:
    """`min_length=1` at the type level, not a runtime check.

    A finding with no citation should be impossible to construct, so no code
    path can produce one and forget to validate it.
    """
    with pytest.raises(pydantic.ValidationError):
        Finding(claim="something happened", cited_trace_ids=())


def test_fabricated_trace_id_is_rejected(window: object) -> None:
    """The core case: a well-formed UUID naming nothing."""
    validator = GroundingValidator(window)  # type: ignore[arg-type]

    with pytest.raises(GroundingError, match="not present in the evidence window"):
        validator.check(finding(cited_trace_ids=(OUT_OF_WINDOW,)))


def test_id_from_a_different_session_is_rejected() -> None:
    """Real elsewhere is not real here.

    The id exists in the store, so a check against the store would pass it —
    but it is outside the window the model was shown, so the model cannot have
    read it and cannot be citing it honestly.
    """
    shown = window_from_events([event(IN_WINDOW)], query="session-a")
    validator = GroundingValidator(shown)

    with pytest.raises(GroundingError):
        validator.check(finding(cited_trace_ids=(ALSO_IN_WINDOW,)))


def test_a_partly_fabricated_citation_list_is_rejected(window: object) -> None:
    """One real id does not launder a fabricated one beside it."""
    validator = GroundingValidator(window)  # type: ignore[arg-type]

    with pytest.raises(GroundingError, match=str(OUT_OF_WINDOW)):
        validator.check(finding(cited_trace_ids=(IN_WINDOW, OUT_OF_WINDOW)))


def test_duplicate_citations_are_rejected(window: object) -> None:
    """Repeating an id inflates apparent support without adding any."""
    validator = GroundingValidator(window)  # type: ignore[arg-type]

    with pytest.raises(GroundingError, match="duplicate"):
        validator.check(finding(cited_trace_ids=(IN_WINDOW, IN_WINDOW)))


def test_a_grounded_finding_passes_unchanged(window: object) -> None:
    validator = GroundingValidator(window)  # type: ignore[arg-type]
    original = finding(cited_trace_ids=(IN_WINDOW, ALSO_IN_WINDOW))

    assert validator.check(original) == original


def test_validate_all_keeps_the_good_and_records_the_bad(window: object) -> None:
    """The intended trade: fewer findings rather than unsupported ones."""
    validator = GroundingValidator(window)  # type: ignore[arg-type]

    outcome = validator.validate_all(
        [
            finding(claim="supported", cited_trace_ids=(IN_WINDOW,)),
            finding(claim="fabricated", cited_trace_ids=(OUT_OF_WINDOW,)),
        ]
    )

    assert [f.claim for f in outcome.accepted] == ["supported"]
    assert outcome.rejected_count == 1
    assert outcome.rejected[0].claim == "fabricated"
    assert str(OUT_OF_WINDOW) in outcome.rejected[0].reason


def test_human_review_is_required_by_default() -> None:
    """Nothing in the platform clears this automatically (ADR-020)."""
    assert finding().human_review_required is True


def test_source_citation_that_escapes_the_repo_is_rejected(window: object, tmp_path: Path) -> None:
    """`../` in a model-produced path is a finding about the model."""
    validator = GroundingValidator(window, repo_root=tmp_path)  # type: ignore[arg-type]

    with pytest.raises(GroundingError, match="escapes the repository root"):
        validator.check(
            finding(cited_sources=(SourceRef(path="../../etc/passwd", start_line=1, end_line=1),))
        )


def test_source_citation_to_a_missing_file_is_rejected(window: object, tmp_path: Path) -> None:
    validator = GroundingValidator(window, repo_root=tmp_path)  # type: ignore[arg-type]

    with pytest.raises(GroundingError, match="does not exist"):
        validator.check(
            finding(cited_sources=(SourceRef(path="nope.py", start_line=1, end_line=2),))
        )


def test_source_citation_past_end_of_file_is_rejected(window: object, tmp_path: Path) -> None:
    """The line range must exist, not just the file."""
    (tmp_path / "short.py").write_text("one\ntwo\n", encoding="utf-8")
    validator = GroundingValidator(window, repo_root=tmp_path)  # type: ignore[arg-type]

    with pytest.raises(GroundingError, match="has 2 lines"):
        validator.check(
            finding(cited_sources=(SourceRef(path="short.py", start_line=99, end_line=100),))
        )


def test_source_citation_that_resolves_is_accepted(window: object, tmp_path: Path) -> None:
    (tmp_path / "real.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    validator = GroundingValidator(window, repo_root=tmp_path)  # type: ignore[arg-type]

    checked = validator.check(
        finding(cited_sources=(SourceRef(path="real.py", start_line=1, end_line=2),))
    )

    assert checked.confidence is Confidence.MEDIUM


def test_unverifiable_source_citation_is_demoted_not_accepted(window: object) -> None:
    """With no repo root the path cannot be checked, so confidence drops.

    Accepting it at face value would let an unconfigured caller publish
    source citations nothing ever verified.
    """
    validator = GroundingValidator(window, repo_root=None)  # type: ignore[arg-type]

    checked = validator.check(
        finding(
            confidence=Confidence.HIGH,
            cited_sources=(SourceRef(path="anything.py", start_line=1, end_line=2),),
        )
    )

    assert checked.confidence is Confidence.LOW


def test_demotion_never_raises_confidence(window: object) -> None:
    validator = GroundingValidator(window, repo_root=None)  # type: ignore[arg-type]

    checked = validator.check(
        finding(
            confidence=Confidence.LOW,
            cited_sources=(SourceRef(path="anything.py", start_line=1, end_line=2),),
        )
    )

    assert checked.confidence is Confidence.LOW
