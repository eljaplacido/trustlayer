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

from datetime import date
from pathlib import Path

import pytest
from compliance.src.evidence_linker import EvidenceLinker
from compliance.src.validation import load_yaml_mapping

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


def test_article_50_catalog_encodes_the_omnibus_timeline_as_data() -> None:
    """The Digital Omnibus deferred Art. 50(2) marking to 2026-12-02 while
    leaving Art. 50(1) in force. Encoding that as `applies_from` rather than
    prose keeps the catalog correct as dates pass — otherwise every scan run
    after a deadline would need a human to remember it had moved.
    """
    catalog = load_yaml_mapping(CONTROLS_DIR / "article-50-v1.yaml")
    controls = {c["id"]: c for a in catalog["articles"] for c in a.get("controls", [])}

    # Compared through `date` because YAML yields a `datetime.date` for an
    # unquoted value and a `str` for a quoted one. A catalog author may
    # reasonably write either, and the engine accepts both, so the test must
    # not pin an incidental representation.
    def commencement(control_id: str) -> date:
        raw = controls[control_id]["applies_from"]
        return raw if isinstance(raw, date) else date.fromisoformat(str(raw))

    # Art. 50(1) disclosure: live today.
    assert commencement("art-50.1.1") == date(2026, 8, 2)
    # Art. 50(2) machine-readable marking: deferred by the Digital Omnibus.
    assert commencement("art-50.3.1") == date(2026, 12, 2)


def test_article_50_controls_are_split_by_role() -> None:
    """Art. 50(3) and 50(4) bind the *deployer*, not the provider. Scoring a
    provider against a deployer's duty is gap G9, and the split has to live in
    the catalog for the engine to honour it.
    """
    catalog = load_yaml_mapping(CONTROLS_DIR / "article-50-v1.yaml")
    controls = {c["id"]: c for a in catalog["articles"] for c in a.get("controls", [])}

    assert controls["art-50.1.1"]["applies_to_roles"] == ["provider"]
    assert controls["art-50.2.1"]["applies_to_roles"] == ["deployer"]
    assert controls["art-50.3.2"]["applies_to_roles"] == ["deployer"]


def test_every_role_annotated_control_cites_its_legal_reference() -> None:
    """A role split a reader cannot check is one they have to trust."""
    catalog = load_yaml_mapping(CONTROLS_DIR / "article-50-v1.yaml")

    for article in catalog["articles"]:
        for control in article.get("controls", []):
            if "applies_to_roles" in control:
                assert control.get("legal_ref"), f"{control['id']} has no legal_ref"
