"""Prompt loading with version + hash (ADR-020 §4).

Prompts are versioned files whose hash is recorded in every run, so a prompt
edit is visible in provenance and the workbench can mark runs from different
prompt versions as not directly comparable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .models import EvaluatorRole

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    role: EvaluatorRole
    version: str
    text: str
    sha256: str


def _parse_version(text: str) -> tuple[str, str]:
    """Split a leading `version: N` line off the prompt body.

    The version lives in the file rather than in a registry so that editing a
    prompt without bumping its version is a visible omission in the diff.
    """
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("version:"):
        version = lines[0].split(":", 1)[1].strip()
        return version or "0", "\n".join(lines[1:]).lstrip("\n")
    return "0", text


@lru_cache(maxsize=None)
def load(role: EvaluatorRole) -> Prompt:
    """Load one role's prompt, with the shared grounding contract appended.

    The contract is concatenated here rather than pasted into each role file so
    that a change to the grounding rules cannot apply to some roles and not
    others — and so it lands in every role's recorded `prompt_hash`.
    """
    path = PROMPT_DIR / f"{role.value}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt file for role {role.value!r} at {path}")
    version, body = _parse_version(path.read_text(encoding="utf-8"))
    shared = load_shared()
    text = f"{body}\n\n{shared.text}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Prompt(role=role, version=f"{version}+g{shared.version}", text=text, sha256=digest)


@lru_cache(maxsize=1)
def load_shared() -> Prompt:
    """The grounding contract every role carries (ADR-020 §3)."""
    path = PROMPT_DIR / "_shared_grounding.md"
    version, body = _parse_version(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return Prompt(role=EvaluatorRole.INSIGHT_ADVISOR, version=version, text=body, sha256=digest)


def all_roles() -> tuple[EvaluatorRole, ...]:
    return tuple(EvaluatorRole)
