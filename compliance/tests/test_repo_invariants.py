"""Repo-level invariants that no single package owns.

These live in the compliance suite because it is the one Python job that runs
repo-wide in CI. Each guards a claim made in an accepted ADR or in the docs —
claims that are easy to state, easy to break silently, and embarrassing to
discover from a fresh clone.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SKILLS = REPO_ROOT / ".opencode" / "skills"
CLAUDE_SKILLS = REPO_ROOT / ".claude" / "skills"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


# --- Agent skills are single-source (ADR-023 §7) ---------------------------


def skill_names() -> list[str]:
    return sorted(p.name for p in CANONICAL_SKILLS.iterdir() if p.is_dir())


def test_there_are_canonical_skills_to_check() -> None:
    """Guard the discovery itself — an empty list would vacuously pass below."""
    assert skill_names()


@pytest.mark.parametrize("name", skill_names())
def test_claude_skill_is_a_symlink_to_the_canonical_one(name: str) -> None:
    """Two copies of a workflow means one is silently wrong and there is no way
    to tell which. ADR-023 §7 makes `.claude/skills/<name>` a symlink so both
    harnesses read one file."""
    link = CLAUDE_SKILLS / name

    assert link.is_symlink(), f"{link} must be a symlink, not a copy"
    assert link.resolve() == (CANONICAL_SKILLS / name).resolve()


@pytest.mark.parametrize("name", skill_names())
def test_claude_skill_symlink_is_tracked_by_git(name: str) -> None:
    """The regression this exists to prevent.

    `.gitignore` excluded all of `.claude/`, so the symlinks existed only on
    the machine that created them. A fresh clone got the OpenCode copies and
    nothing for Claude Code — exactly the drift ADR-023 §7 exists to prevent,
    and invisible to anyone who did not clone the repo.

    Mode `120000` is git's symlink mode. Asserting it (rather than mere
    tracking) also catches a checkout that materialised the link as a regular
    file containing a path.
    """
    entry = git("ls-files", "-s", f".claude/skills/{name}").strip()

    assert entry, f".claude/skills/{name} is not tracked by git"
    assert entry.startswith("120000"), f"tracked but not as a symlink: {entry}"


def test_claude_settings_stay_untracked() -> None:
    """Machine-local settings must not ride along with the skills fix."""
    tracked = git("ls-files", ".claude").splitlines()

    leaked = [p for p in tracked if not p.startswith(".claude/skills/")]
    assert not leaked, f"machine-local .claude files are tracked: {leaked}"


# --- ADR hygiene -----------------------------------------------------------


def adr_paths() -> list[Path]:
    return sorted((REPO_ROOT / "obsidian_vault" / "01_Architecture").glob("ADR-*.md"))


def test_every_adr_declares_a_status() -> None:
    """An ADR with no status cannot be told from one nobody decided on."""
    missing = [
        p.name
        for p in adr_paths()
        if not re.search(r"^status:", p.read_text(encoding="utf-8"), re.MULTILINE)
    ]

    assert not missing, f"ADRs with no status: {missing}"


def test_phase_8_adr_index_lists_every_phase_8_adr() -> None:
    """The design doc's index is how a reader finds the ADRs. One missing entry
    makes a decision invisible to anyone starting from the map."""
    design = (REPO_ROOT / "docs" / "PHASE-8-DESIGN.md").read_text(encoding="utf-8")
    indexed = set(re.findall(r"\| (ADR-\d+) \|", design))

    on_disk = {
        m.group(0)
        for p in adr_paths()
        if (m := re.match(r"ADR-\d+", p.name)) and int(m.group(0)[4:]) >= 17
    }

    assert on_disk <= indexed, f"Phase 8 ADRs missing from the index: {sorted(on_disk - indexed)}"


# --- Schema / spec hygiene -------------------------------------------------


def test_spec_states_the_event_type_count_consistently() -> None:
    """Three documents quote the count in prose. G0 happened because one of
    them said 'seven' after the set grew to nine."""
    schema_rs = (REPO_ROOT / "core-rs" / "src" / "schema.rs").read_text(encoding="utf-8")
    block = re.search(r"pub enum EventType \{(.*?)\}", schema_rs, re.DOTALL)
    assert block
    count = len(re.findall(r"^\s*([A-Z][A-Za-z0-9]*),\s*$", block.group(1), re.MULTILINE))

    words = {
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
        11: "eleven",
        12: "twelve",
        13: "thirteen",
    }
    expected = words.get(count)
    assert expected, f"no spelled-out word for {count}; extend the map"

    for relative in (
        "spec/v0.1/01-wire-format.md",
        "spec/v0.1/02-event-types.md",
        "spec/v0.1/06-conformance.md",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        stale = {w for n, w in words.items() if n != count and f"the {w} " in text}
        assert not stale, f"{relative} quotes a stale event-type count: {sorted(stale)}"


def test_every_committed_event_fixture_is_listed_in_the_readme() -> None:
    """A fixture nobody documented is one nobody knows to regenerate."""
    fixtures_dir = REPO_ROOT / "spec" / "v0.1" / "fixtures"
    readme = (fixtures_dir / "README.md").read_text(encoding="utf-8")

    undocumented = [
        p.name for p in sorted(fixtures_dir.glob("event-*.json")) if f"`{p.name}`" not in readme
    ]

    assert not undocumented, f"fixtures missing from the README table: {undocumented}"


def test_predicate_conformance_table_is_read_by_both_implementations() -> None:
    """One table, two engines. If only one suite reads it, the languages can
    diverge exactly as they did in G0."""
    table = REPO_ROOT / "spec" / "v0.1" / "fixtures" / "predicate-cases.json"
    assert table.exists()
    # Non-trivial: an empty table would satisfy every reader vacuously.
    assert len(json.loads(table.read_text(encoding="utf-8"))["cases"]) >= 20

    rust = (REPO_ROOT / "core-rs" / "tests" / "predicate_conformance.rs").read_text(
        encoding="utf-8"
    )
    python = (REPO_ROOT / "compliance" / "tests" / "test_predicates.py").read_text(encoding="utf-8")

    assert "predicate-cases.json" in rust
    assert "predicate-cases.json" in python
