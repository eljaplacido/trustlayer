"""Every shipped control catalog must load.

This closes the bug class behind G0 (see `docs/PHASE-8-DESIGN.md`):
`article-50-v1.yaml` shipped in Phase 7 referencing `DISCLOSURE_SHOWN`,
while `control.schema.json` still enumerated only the seven pre-Phase-7
event types. Loading that catalog raised `ValidationError`, so it was
dead code — and no test noticed, because the readiness scanner uses
hardcoded `art-50.x` checks and never loads it.

Parametrising over the directory (rather than naming catalogs) means a
future catalog is covered the moment it is committed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from compliance.src.evidence_linker import EvidenceLinker

CONTROLS_DIR = Path(__file__).resolve().parents[1] / "controls"


def _catalog_paths() -> list[Path]:
    return sorted(p for p in CONTROLS_DIR.glob("*.yaml"))


def test_controls_directory_is_not_empty() -> None:
    """Guard the guard: an empty glob would make the suite below vacuous."""
    assert _catalog_paths(), f"no control catalogs found in {CONTROLS_DIR}"


@pytest.mark.parametrize("catalog", _catalog_paths(), ids=lambda p: p.name)
def test_shipped_catalog_loads_and_validates(catalog: Path) -> None:
    framework = EvidenceLinker().load_control_framework(catalog)

    assert framework["framework"], f"{catalog.name}: empty framework name"
    assert framework["articles"], f"{catalog.name}: no articles"


@pytest.mark.parametrize("catalog", _catalog_paths(), ids=lambda p: p.name)
def test_shipped_catalog_control_ids_are_unique(catalog: Path) -> None:
    framework = EvidenceLinker().load_control_framework(catalog)

    seen: dict[str, str] = {}
    for article in framework["articles"]:
        for control in article.get("controls", []):
            control_id = control["id"]
            assert control_id not in seen, (
                f"{catalog.name}: duplicate control id {control_id!r} "
                f"in articles {seen[control_id]!r} and {article['id']!r}"
            )
            seen[control_id] = article["id"]
