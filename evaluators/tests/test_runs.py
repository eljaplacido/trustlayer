"""Run records are Art. 12 evidence — where they land must be knowable."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from trustlayer_eval import runs
from trustlayer_eval.models import (
    EgressDecision,
    EvaluatorRole,
    EvaluatorRun,
    EvidenceWindowRef,
    Residency,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def a_run() -> EvaluatorRun:
    return EvaluatorRun(
        role=EvaluatorRole.INSIGHT_ADVISOR,
        provider="ollama",
        model="m",
        prompt_hash="0" * 64,
        prompt_version="1",
        evidence_window=EvidenceWindowRef(query="q", result_hash="a" * 64, event_count=1),
        duration_ms=1.0,
        egress=EgressDecision(
            allowed=True, provider="ollama", residency=Residency.LOCAL, reason="local"
        ),
    )


def test_the_runs_directory_is_always_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative path resolves against whichever directory the writing process
    started in — which is how one deployment ends up with run logs in three
    places and a complete one nowhere."""
    monkeypatch.delenv(runs.RUNS_DIR_ENV_VAR, raising=False)

    assert runs.runs_dir().is_absolute()


def test_the_runs_directory_is_configurable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(runs.RUNS_DIR_ENV_VAR, str(tmp_path / "elsewhere"))

    assert runs.runs_dir() == (tmp_path / "elsewhere").resolve()


def test_a_run_round_trips_through_the_log(tmp_path: Path) -> None:
    path = runs.append(a_run(), runs_dir_override=tmp_path)

    recovered = list(runs.read(path))

    assert len(recovered) == 1
    assert recovered[0].role is EvaluatorRole.INSIGHT_ADVISOR


def test_an_unparseable_line_does_not_destroy_the_log(tmp_path: Path) -> None:
    """A schema change must not retroactively make old evidence unreadable."""
    path = runs.append(a_run(), runs_dir_override=tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"role": "from-a-future-schema"}\n')
    runs.append(a_run(), runs_dir_override=tmp_path)

    assert len(list(runs.read(path))) == 2


@pytest.mark.parametrize(
    "candidate",
    [
        "compliance/runs/insight_advisor.jsonl",
        "dashboard/compliance/runs/insight_advisor.jsonl",
        "evaluators/compliance/runs/insight_advisor.jsonl",
    ],
)
def test_run_records_are_git_ignored_wherever_they_land(candidate: str) -> None:
    """Records carry real trace ids and findings from whatever system was
    scanned. The default location follows the writing process's working
    directory, so the ignore rule has to be depth-independent — anchoring it to
    the repo root would ignore one location and silently track the rest.
    """
    result = subprocess.run(["git", "check-ignore", "-q", candidate], cwd=REPO_ROOT, check=False)

    assert result.returncode == 0, f"{candidate} would be committed"
