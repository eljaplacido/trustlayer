"""The event-type set must stay in lockstep across every layer.

Working agreement 3 requires the SDKs to mirror the schema byte-for-byte.
Phase 7 added `DISCLOSURE_SHOWN` and `CONTENT_MARKED` to all four SDKs and
to `core-rs`, but not to the normative spec or to
`compliance/schemas/control.schema.json` — which silently made the Article
50 catalog unloadable (G0).

These tests treat the reference Rust core as the single source of truth and
assert the spec prose and the compliance schema agree with it. Parsing the
sources directly keeps the check dependency-free: the compliance package
does not (and should not need to) import the Python SDK.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUST_SCHEMA = REPO_ROOT / "core-rs" / "src" / "schema.rs"
SPEC_EVENT_TYPES = REPO_ROOT / "spec" / "v0.1" / "02-event-types.md"
CONTROL_SCHEMA = REPO_ROOT / "compliance" / "schemas" / "control.schema.json"

_ENUM_BLOCK = re.compile(r"pub enum EventType \{(.*?)\}", re.DOTALL)
_VARIANT = re.compile(r"^\s*([A-Z][A-Za-z0-9]*),\s*$", re.MULTILINE)
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _screaming_snake(variant: str) -> str:
    """`LlmCall` -> `LLM_CALL`, matching serde's SCREAMING_SNAKE_CASE rename."""
    return _CAMEL_BOUNDARY.sub("_", variant).upper()


def reference_event_types() -> list[str]:
    """The v0.1 event-type set, read from the reference Rust implementation."""
    block = _ENUM_BLOCK.search(RUST_SCHEMA.read_text(encoding="utf-8"))
    assert block is not None, f"could not locate `pub enum EventType` in {RUST_SCHEMA}"
    variants = _VARIANT.findall(block.group(1))
    assert variants, f"no variants parsed from EventType in {RUST_SCHEMA}"
    return [_screaming_snake(v) for v in variants]


def test_reference_parse_is_sane() -> None:
    """Guard the parser itself — a silent regex failure would void every test below."""
    event_types = reference_event_types()

    assert "AGENT_START" in event_types
    assert "LLM_CALL" in event_types, "CamelCase -> SCREAMING_SNAKE_CASE conversion is wrong"
    assert len(event_types) == len(set(event_types)), "duplicate variants parsed"


def test_control_schema_enum_matches_reference() -> None:
    schema = json.loads(CONTROL_SCHEMA.read_text(encoding="utf-8"))
    enum = schema["properties"]["articles"]["items"]["properties"]["controls"]["items"][
        "properties"
    ]["evidence_query"]["properties"]["event_types"]["items"]["enum"]

    assert sorted(enum) == sorted(reference_event_types()), (
        "control.schema.json event_types enum has drifted from core-rs EventType. "
        "A catalog referencing a missing value fails to load (see G0)."
    )


def test_spec_enum_table_matches_reference() -> None:
    """The normative spec must define every event type the SDKs emit."""
    spec = SPEC_EVENT_TYPES.read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([A-Z_]+)` \| \[§", spec, re.MULTILINE))

    assert documented == set(reference_event_types()), (
        "spec/v0.1/02-event-types.md enum table has drifted from core-rs EventType"
    )


@pytest.mark.parametrize("event_type", reference_event_types())
def test_spec_defines_a_payload_contract_for_each_event_type(event_type: str) -> None:
    spec = SPEC_EVENT_TYPES.read_text(encoding="utf-8")

    assert re.search(rf"^## 2\.\d+ `{event_type}`", spec, re.MULTILINE), (
        f"spec/v0.1/02-event-types.md has no payload contract section for {event_type}"
    )
