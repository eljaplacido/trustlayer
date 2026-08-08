"""Runs the shared predicate conformance table (spec §4.3, ADR-018).

The same `spec/v0.1/fixtures/predicate-cases.json` drives
`core-rs/tests/predicate_conformance.rs`. One table, two implementations —
because a predicate language implemented twice and tested twice will diverge,
and divergence between the policy engine and the evidence engine means a
control can claim to be enforced by a rule that does not match the same events.
That is gap G0 one layer up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from compliance.src.predicates import (
    MISSING,
    matches_predicate,
    matches_where,
    resolve_path,
    validate_predicate,
    validate_where,
)

TABLE_PATH = (
    Path(__file__).resolve().parents[2] / "spec" / "v0.1" / "fixtures" / "predicate-cases.json"
)


def load_table() -> dict[str, Any]:
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


TABLE = load_table()
CASES = TABLE["cases"]
VALIDATION_CASES = TABLE["validation_cases"]


def test_the_table_is_populated() -> None:
    """Guard the loader — a bad path would silently skip every case below."""
    assert CASES
    assert VALIDATION_CASES


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_shared_evaluation_table_holds(case: dict[str, Any]) -> None:
    # An omitted `actual` means the dotted path did not resolve. That is
    # distinct from `actual: null`, and the difference is what $exists tests.
    actual = case.get("actual", MISSING)

    assert matches_predicate(actual, case["expected"]) is case["matches"]


@pytest.mark.parametrize("case", VALIDATION_CASES, ids=lambda c: c["name"])
def test_shared_validation_table_holds(case: dict[str, Any]) -> None:
    reason = validate_predicate("p", case["expected"])

    assert (reason is None) is case["valid"], reason


def test_case_names_are_unique() -> None:
    names = [c["name"] for c in CASES]

    assert len(names) == len(set(names)), "duplicate case names make failures ambiguous"


# --- path resolution -------------------------------------------------------


def test_resolve_path_walks_nested_objects() -> None:
    payload = {"a": {"b": {"c": 1}}}

    assert resolve_path(payload, "a.b.c") == 1


def test_resolve_path_indexes_arrays_by_numeric_segment() -> None:
    payload = {"args": {"tools": ["shell", "python"]}}

    assert resolve_path(payload, "args.tools.0") == "shell"
    assert resolve_path(payload, "args.tools.1") == "python"


def test_resolve_path_reports_missing_rather_than_none() -> None:
    """`None` is a legitimate JSON value; conflating it with absence would make
    `$exists` meaningless."""
    payload = {"a": None}

    assert resolve_path(payload, "a") is None
    assert resolve_path(payload, "b") is MISSING
    assert resolve_path(payload, "a.b") is MISSING


def test_resolve_path_stops_at_a_scalar() -> None:
    payload = {"a": "string"}

    assert resolve_path(payload, "a.b") is MISSING


def test_resolve_path_rejects_an_out_of_range_index() -> None:
    payload = {"a": [1]}

    assert resolve_path(payload, "a.5") is MISSING
    assert resolve_path(payload, "a.-1") is MISSING


# --- where clauses ---------------------------------------------------------


def test_where_ands_every_predicate() -> None:
    payload = {"tool_name": "payments.transfer", "amount": 500}

    assert matches_where(payload, {"tool_name": "payments.transfer", "amount": {"$gt": 100}})
    assert not matches_where(payload, {"tool_name": "payments.transfer", "amount": {"$gt": 900}})


def test_empty_where_matches_everything() -> None:
    assert matches_where({}, {})
    assert matches_where({"a": 1}, {})


def test_validate_where_reports_every_problem_at_once() -> None:
    """One round of fixes, not one commit per error."""
    problems = validate_where({"a": {"$gt": "x"}, "b": {"$nope": 1}, "c": {"$in": "not-a-list"}})

    assert len(problems) == 3


def test_validate_where_is_silent_on_a_clean_clause() -> None:
    assert validate_where({"a": 1, "b": {"$in": ["x"]}}) == []


# --- booleans are not numbers ----------------------------------------------


def test_booleans_are_not_treated_as_numbers() -> None:
    """Python makes `True == 1`; a control comparing `enabled: {"$gt": 0}`
    must not silently succeed on a boolean."""
    assert not matches_predicate(True, {"$gt": 0})
    assert not matches_predicate(True, {"$gte": 1})


def test_boolean_membership_does_not_collapse_into_integers() -> None:
    assert not matches_predicate(True, {"$in": [1]})
    assert matches_predicate(True, {"$in": [True]})
