"""Run-record persistence (ADR-020 §7).

Persisted as JSONL under `compliance/runs/`. The run record is itself Art. 12
evidence about the tooling: it says which model saw which evidence, under which
prompt version, and what was suppressed as ungrounded.

Because it is evidence, *where* it lands cannot depend on which directory the
process happened to start in — records scattered across half a dozen
`compliance/runs/` directories are not an audit trail. The location is resolved
once, from `TRUSTLAYER_EVAL_RUNS_DIR`, and reported by the service's `/health`
so it is never a mystery.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from .models import EvaluatorRun

RUNS_DIR_ENV_VAR = "TRUSTLAYER_EVAL_RUNS_DIR"
DEFAULT_RUNS_DIR = "compliance/runs"


def runs_dir(override: Path | None = None) -> Path:
    """Absolute directory for run records.

    Always absolute: a relative path here would resolve against the working
    directory of whatever process wrote the record, which is how the same
    deployment ends up with run logs in three places and a complete one
    nowhere.
    """
    if override is not None:
        return override.expanduser().resolve()
    configured = os.environ.get(RUNS_DIR_ENV_VAR, "").strip()
    return Path(configured or DEFAULT_RUNS_DIR).expanduser().resolve()


def append(run: EvaluatorRun, *, runs_dir_override: Path | None = None) -> Path:
    """Append one run record. Returns the file it landed in."""
    directory = runs_dir(runs_dir_override)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.role.value}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(run.to_jsonl())
        handle.write("\n")
    return path


def read(path: Path) -> Iterator[EvaluatorRun]:
    """Read run records, skipping lines that no longer parse.

    A record written by an older schema is not a reason to fail the whole read:
    the point of the log is that old entries stay readable, and a strict parse
    would make a schema change retroactively destroy the audit trail.
    """
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield EvaluatorRun.model_validate_json(line)
            except ValidationError:
                continue
