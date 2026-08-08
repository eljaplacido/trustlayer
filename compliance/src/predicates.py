"""Payload predicate evaluation — the Python mirror of `core-rs/src/predicate.rs`.

One predicate language serves both the policy engine and the evidence engine
(design principle P6). Controls and policies therefore speak the same dialect,
which is what lets a control reference the policy that enforces it, and lets a
gap be remediated by emitting a rule from the same predicate.

**This file and `core-rs/src/predicate.rs` are a matched pair.** Divergence is
the exact failure class that produced gap G0, so `test_predicates.py` runs a
shared table of cases and the Rust suite runs the same table. Change one, change
both, in the same commit.

Semantics, in brief:

* A literal expected-value means deep equality against the dotted path's
  resolved value — v0.1 behaviour, unchanged.
* An object whose keys *all* start with `$` is an operator expression.
* A mixed object is rejected by `validate_predicate`, never silently treated as
  a literal: `{"$gt": 5, "unit": "ms"}` would otherwise become a comparison
  that can never match, and a predicate that never matches is one nobody
  notices is broken.
* There is no regular-expression operator. `$prefix` and `$suffix` cover what
  catalogs need, and a regex evaluated over a million events on behalf of a
  user-supplied catalog is a denial-of-service primitive.
"""

from __future__ import annotations

from typing import Any, Final

#: Sentinel for "the dotted path did not resolve". `None` cannot be used: JSON
#: null is a legitimate value, and conflating "absent" with "present and null"
#: would make `$exists` meaningless.
MISSING: Final = object()

OPERATORS: Final[frozenset[str]] = frozenset(
    {
        "$eq",
        "$ne",
        "$in",
        "$nin",
        "$gt",
        "$gte",
        "$lt",
        "$lte",
        "$exists",
        "$contains",
        "$prefix",
        "$suffix",
    }
)

_ARRAY_OPERANDS: Final[frozenset[str]] = frozenset({"$in", "$nin"})
_NUMERIC_OPERANDS: Final[frozenset[str]] = frozenset({"$gt", "$gte", "$lt", "$lte"})
_STRING_OPERANDS: Final[frozenset[str]] = frozenset({"$prefix", "$suffix"})


def resolve_path(payload: dict[str, Any], path: str) -> Any:
    """Walk `payload` along a dotted path; numeric segments index arrays.

    Returns `MISSING` when any segment is absent or traverses a scalar. Mirrors
    `resolve_path` in `core-rs/src/policy.rs`.
    """
    segments = path.split(".")
    current: Any = payload
    for segment in segments:
        if isinstance(current, dict):
            if segment not in current:
                return MISSING
            current = current[segment]
        elif isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                return MISSING
            if index < 0 or index >= len(current):
                return MISSING
            current = current[index]
        else:
            return MISSING
    return current


def is_operator_object(expected: Any) -> bool:
    """Is this an operator expression rather than a literal?"""
    return (
        isinstance(expected, dict)
        and len(expected) > 0
        and all(key.startswith("$") for key in expected)
    )


def validate_predicate(path: str, expected: Any) -> str | None:
    """Reject predicates that would mean something other than intended.

    Returns a human-readable reason, or `None` when well formed. Callers
    validate at load time so evaluation stays a plain boolean.
    """
    if not isinstance(expected, dict) or not expected:
        return None

    dollar = [key for key in expected if key.startswith("$")]
    if not dollar:
        return None  # a plain object literal; deep equality

    if len(dollar) != len(expected):
        plain = sorted(key for key in expected if not key.startswith("$"))
        return (
            f"predicate for {path!r} mixes operators with literal keys ({plain}). "
            "Either make every key an operator, or none — a mixed object would "
            "be compared literally and could never match."
        )

    for key in dollar:
        if key not in OPERATORS:
            return (
                f"predicate for {path!r} uses unknown operator {key!r}. Known: {sorted(OPERATORS)}"
            )

    # Operand types. Caught here rather than at evaluation, where a wrong type
    # would just silently fail to match every event.
    for key, operand in expected.items():
        if key in _ARRAY_OPERANDS and not isinstance(operand, list):
            return f"predicate for {path!r}: operator {key} needs an array operand"
        if key in _NUMERIC_OPERANDS and (
            isinstance(operand, bool) or not isinstance(operand, (int, float))
        ):
            return f"predicate for {path!r}: operator {key} needs a numeric operand"
        if key == "$exists" and not isinstance(operand, bool):
            return f"predicate for {path!r}: operator $exists needs a boolean operand"
        if key in _STRING_OPERANDS and not isinstance(operand, str):
            return f"predicate for {path!r}: operator {key} needs a string operand"
    return None


def _as_number(value: Any) -> float | None:
    """Numeric view of a value, or None.

    Booleans are excluded deliberately: Python makes `True == 1`, and a control
    comparing `enabled: {"$gt": 0}` should not silently succeed.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def matches_predicate(actual: Any, expected: Any) -> bool:
    """Evaluate one predicate against a resolved value.

    `actual` is `MISSING` when the path did not resolve. A missing path fails
    every operator except `$exists: false` and `$ne` — asserting that an absent
    field differs from a value is true, and is how a control expresses "this
    must not be set to X".
    """
    if not is_operator_object(expected):
        return actual is not MISSING and actual == expected

    present = actual is not MISSING

    for operator, operand in expected.items():
        if operator == "$exists":
            if operand is not present:
                return False
        elif operator == "$eq":
            if not present or actual != operand:
                return False
        elif operator == "$ne":
            if present and actual == operand:
                return False
        elif operator == "$in":
            if not present or not _contains_value(operand, actual):
                return False
        elif operator == "$nin":
            if present and _contains_value(operand, actual):
                return False
        elif operator in _NUMERIC_OPERANDS:
            left = _as_number(actual) if present else None
            right = _as_number(operand)
            if left is None or right is None or not _compare(operator, left, right):
                return False
        elif operator == "$prefix":
            if not (present and isinstance(actual, str) and actual.startswith(operand)):
                return False
        elif operator == "$suffix":
            if not (present and isinstance(actual, str) and actual.endswith(operand)):
                return False
        elif operator == "$contains":
            if not _matches_contains(actual if present else MISSING, operand):
                return False
        else:
            # Unknown operators are rejected at validation time; refusing to
            # match means one that slipped through cannot silently pass.
            return False
    return True


def _contains_value(operand: Any, actual: Any) -> bool:
    """Membership that does not treat `True` as `1`."""
    if not isinstance(operand, list):
        return False
    return any(
        item == actual and isinstance(item, bool) == isinstance(actual, bool) for item in operand
    )


def _compare(operator: str, left: float, right: float) -> bool:
    if operator == "$gt":
        return left > right
    if operator == "$gte":
        return left >= right
    if operator == "$lt":
        return left < right
    return left <= right


def _matches_contains(actual: Any, operand: Any) -> bool:
    if isinstance(actual, str):
        return isinstance(operand, str) and operand in actual
    if isinstance(actual, list):
        return any(item == operand for item in actual)
    return False


def matches_where(payload: dict[str, Any], where: dict[str, Any]) -> bool:
    """Every dotted-path predicate in `where` must hold (implicit AND).

    Matches how `MatchSpec` already ANDs its fields in the policy engine.
    """
    return all(
        matches_predicate(resolve_path(payload, path), expected) for path, expected in where.items()
    )


def validate_where(where: dict[str, Any], *, context: str = "where") -> list[str]:
    """Validate a whole `where` clause. Returns every problem, not just the first.

    Reporting all of them means a catalog author fixes one round of errors
    rather than discovering them one commit at a time.
    """
    problems: list[str] = []
    for path, expected in where.items():
        reason = validate_predicate(path, expected)
        if reason:
            problems.append(f"{context}: {reason}")
    return problems
