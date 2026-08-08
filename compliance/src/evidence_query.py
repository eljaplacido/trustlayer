"""Evidence query v2 and assurance tiers (ADR-018).

v1 asked one question: "does an event of this shape exist at least N times?"
Presence is not compliance.

* Art. 14 is not satisfied by the existence of one `HUMAN_ESCALATION`. It asks
  whether oversight was *effective* — whether escalations were resolved, by
  whom, and how fast.
* Art. 15 is not satisfied by the existence of a passing `POLICY_CHECK`. It
  asks whether **every** risky action was gated.
* An auditor asks what proportion of the population is covered, not whether it
  happened once.

So v2 adds four predicate forms over the event stream — `coverage`, `sequence`,
`absence`, `resolution` — and replaces the `satisfied: bool` with a tier.

## Why tiers rather than a percentage

Gap G4: a field-presence check yields 100%, and publishing that as "readiness"
invites a bad surprise in a real assessment. A single blended number cannot
distinguish "we wrote it down" from "the runtime proves it", so this module
refuses to blend them. `AssuranceReport` reports the three counts separately
and has no combined score to print.

Everything here is deterministic (P2). A control the engine cannot decide is
`INDETERMINATE` — an honest verdict, and the only input a model layer is ever
allowed to see (ADR-020).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from compliance.src.predicates import matches_where, validate_where

#: Suffix multipliers for duration strings like `5s`, `24h`, `90d`.
_DURATION_UNITS: dict[str, int] = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class AssuranceTier(StrEnum):
    """How well a control is supported. Ordered weakest to strongest.

    The distinction between DECLARED and EVIDENCED is the whole point: one is
    an assertion by the party being assessed, the other is a fact about what
    the system did.
    """

    UNKNOWN = "unknown"
    """Not assessed. Distinct from a failure — silence is not a negative."""

    DECLARED = "declared"
    """Asserted in `system.yaml` or a document. Nothing observed it."""

    EVIDENCED = "evidenced"
    """A deterministic query over runtime traces supports it."""

    VERIFIED = "verified"
    """Evidenced, integrity-checked, and independently confirmed."""


#: Rank for comparison. A dict rather than enum order so the intent is explicit
#: at the point a comparison is made.
_TIER_RANK: dict[AssuranceTier, int] = {
    AssuranceTier.UNKNOWN: 0,
    AssuranceTier.DECLARED: 1,
    AssuranceTier.EVIDENCED: 2,
    AssuranceTier.VERIFIED: 3,
}


def tier_at_least(tier: AssuranceTier, floor: AssuranceTier) -> bool:
    """Does `tier` meet or exceed `floor`? Used by the `--min-assurance` gate."""
    return _TIER_RANK[tier] >= _TIER_RANK[floor]


class Determination(StrEnum):
    """Who or what decided. Never inferred — always recorded."""

    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
    HUMAN = "human"


class IntegrityStatus(StrEnum):
    """Whether the supporting events sit in a chain that verifies (ADR-017)."""

    VERIFIED = "verified"
    UNCHAINED = "unchained"
    """No chain covers these events. Honest about what predates the feature."""
    FAILED = "failed"
    """A chain exists and does not verify. A finding, not a warning."""
    NOT_CHECKED = "not_checked"


class QueryOutcome(StrEnum):
    """The deterministic engine's verdict on one query."""

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    INDETERMINATE = "indeterminate"
    """Cannot decide: empty population, no query, evidence outside retention.

    Kept distinct from UNSATISFIED because "we cannot tell" and "we checked and
    it failed" call for different actions, and only the former is eligible for
    model assistance (P2).
    """


@dataclass(frozen=True)
class Violation:
    """One concrete failure, citing the events that show it (P1)."""

    reason: str
    trace_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "trace_ids": list(self.trace_ids)}


@dataclass(frozen=True)
class QueryResult:
    """Outcome of evaluating one evidence query."""

    outcome: QueryOutcome
    population: int
    """Events the control is *about* — the denominator."""
    satisfied_count: int
    coverage_ratio: float | None
    violations: tuple[Violation, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": str(self.outcome),
            "population": self.population,
            "satisfied_count": self.satisfied_count,
            "coverage_ratio": self.coverage_ratio,
            "violations": [v.to_dict() for v in self.violations],
            "reason": self.reason,
        }


def parse_duration(value: str | float) -> timedelta:
    """Parse `5s`, `10m`, `24h`, `90d`, or a bare number of seconds."""
    if isinstance(value, (int, float)):
        return timedelta(seconds=float(value))
    raw = value.strip()
    if not raw:
        raise ValueError("empty duration")
    unit = raw[-1].lower()
    if unit in _DURATION_UNITS:
        try:
            magnitude = float(raw[:-1])
        except ValueError as exc:
            raise ValueError(f"malformed duration {value!r}") from exc
        return timedelta(seconds=magnitude * _DURATION_UNITS[unit])
    try:
        return timedelta(seconds=float(raw))
    except ValueError as exc:
        raise ValueError(f"malformed duration {value!r}") from exc


def event_time(event: dict[str, Any]) -> datetime | None:
    """Parse an event's timestamp, or None when it is absent or malformed.

    Returning None rather than raising keeps one bad event from failing an
    entire query; the temporal predicates treat an untimed event as one they
    cannot place, which surfaces as INDETERMINATE rather than as a pass.
    """
    raw = event.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        # Python 3.11+ parses a trailing 'Z' natively.
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _matches(event: dict[str, Any], spec: dict[str, Any]) -> bool:
    """Does one event match a `{event_type, where}` selector?"""
    wanted = spec.get("event_type")
    if wanted is not None and event.get("event_type") != wanted:
        return False
    types = spec.get("event_types")
    if types and event.get("event_type") not in types:
        return False
    where = spec.get("where") or {}
    return not where or matches_where(event.get("payload") or {}, where)


def _select(events: Sequence[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in events if _matches(e, spec)]


def _trace_ids(events: Iterable[dict[str, Any]], limit: int = 10) -> tuple[str, ...]:
    """Cite at most `limit` ids — enough to investigate, not a data dump (P7)."""
    out: list[str] = []
    for event in events:
        trace_id = event.get("trace_id")
        if isinstance(trace_id, str):
            out.append(trace_id)
        if len(out) >= limit:
            break
    return tuple(out)


@dataclass
class EvidenceQuery:
    """A parsed v2 evidence query.

    v1 fields keep their exact meaning, so every existing catalog stays valid
    and produces the same answer it did before.
    """

    raw: dict[str, Any]

    # --- v1 ---
    event_types: list[str] = field(default_factory=list)
    min_count: int = 1
    where: dict[str, Any] = field(default_factory=dict)

    # --- v2 ---
    coverage: dict[str, Any] | None = None
    sequence: list[dict[str, Any]] = field(default_factory=list)
    absence: dict[str, Any] | None = None
    resolution: dict[str, Any] | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> EvidenceQuery:
        # `payload_filters` is the deprecated v1 spelling. It lowers to `where`
        # rather than being evaluated separately, so there is exactly one code
        # path and a v1 catalog cannot drift from a v2 one.
        where: dict[str, Any] = dict(raw.get("payload_filters") or {})
        where.update(raw.get("where") or {})

        return cls(
            raw=raw,
            event_types=list(raw.get("event_types") or []),
            min_count=int(raw.get("min_count", 1)),
            where=where,
            coverage=raw.get("coverage"),
            sequence=list(raw.get("sequence") or []),
            absence=raw.get("absence"),
            resolution=raw.get("resolution"),
        )

    def validate(self) -> list[str]:
        """Every problem with this query, so an author fixes one round of them."""
        problems = validate_where(self.where, context="evidence_query.where")

        # `scope` and `window` are in the schema but the evaluator does not
        # honour them yet. Rejecting is the honest behaviour: a query silently
        # evaluated over a wider set than its author asked for produces a
        # compliance answer to a question nobody posed, and the author has no
        # way to tell. Better a loud error than a quiet mismatch.
        scope = self.raw.get("scope")
        if scope is not None and scope != "system":
            problems.append(
                f"evidence_query.scope={scope!r} is not implemented yet; only "
                "'system' is honoured. Remove it rather than have the query "
                "silently evaluate over a different set than you asked for."
            )
        if self.raw.get("window") is not None:
            problems.append(
                "evidence_query.window is not implemented yet; the query would "
                "silently evaluate over the full retained history instead."
            )
        for index, step in enumerate(self.sequence):
            problems += validate_where(
                (step.get("match") or {}).get("where") or {},
                context=f"evidence_query.sequence[{index}].match.where",
            )
            preceding = step.get("requires_preceding") or {}
            problems += validate_where(
                (preceding.get("match") or {}).get("where") or {},
                context=f"evidence_query.sequence[{index}].requires_preceding.match.where",
            )
            if "within" in preceding:
                try:
                    parse_duration(preceding["within"])
                except ValueError as exc:
                    problems.append(f"evidence_query.sequence[{index}].requires_preceding: {exc}")
        if self.coverage:
            problems += validate_where(
                (self.coverage.get("of") or {}).get("where") or {},
                context="evidence_query.coverage.of.where",
            )
            ratio = self.coverage.get("min_ratio")
            if ratio is not None and not (0.0 <= float(ratio) <= 1.0):
                problems.append("evidence_query.coverage.min_ratio must be between 0 and 1")
        if self.absence:
            problems += validate_where(
                self.absence.get("where") or {}, context="evidence_query.absence.where"
            )
        if self.resolution:
            for key in ("opens_with", "closes_with"):
                problems += validate_where(
                    (self.resolution.get(key) or {}).get("where") or {},
                    context=f"evidence_query.resolution.{key}.where",
                )
            if "within" in self.resolution:
                try:
                    parse_duration(self.resolution["within"])
                except ValueError as exc:
                    problems.append(f"evidence_query.resolution: {exc}")
        return problems

    @property
    def is_v2(self) -> bool:
        return bool(self.coverage or self.sequence or self.absence or self.resolution)

    def evaluate(self, events: Sequence[dict[str, Any]]) -> QueryResult:
        """Run the query. Deterministic, and INDETERMINATE when it cannot decide.

        v2 predicates are evaluated in order of how strong a claim they make;
        the first one present decides. A query carrying several is unusual and
        almost always an authoring mistake, so validation is where that should
        be caught, not here.
        """
        if self.absence is not None:
            return self._evaluate_absence(events)
        if self.resolution is not None:
            return self._evaluate_resolution(events)
        if self.coverage is not None:
            return self._evaluate_coverage(events)
        if self.sequence:
            return self._evaluate_sequence(events, self.sequence)
        return self._evaluate_presence(events)

    # --- v1 -----------------------------------------------------------------

    def _evaluate_presence(self, events: Sequence[dict[str, Any]]) -> QueryResult:
        matching = _select(events, {"event_types": self.event_types, "where": self.where})
        satisfied = len(matching) >= self.min_count
        return QueryResult(
            outcome=QueryOutcome.SATISFIED if satisfied else QueryOutcome.UNSATISFIED,
            population=len(events),
            satisfied_count=len(matching),
            coverage_ratio=None,
            reason=(
                None
                if satisfied
                else f"found {len(matching)} matching events, need at least {self.min_count}"
            ),
        )

    # --- v2 -----------------------------------------------------------------

    def _evaluate_absence(self, events: Sequence[dict[str, Any]]) -> QueryResult:
        """A negative assertion: none of these events may exist.

        Never INDETERMINATE on an empty stream — "no events at all" genuinely
        satisfies "none of this kind happened". The risk of over-claiming from
        an empty log is handled at the tier level, where an absence result over
        zero events cannot reach VERIFIED.
        """
        assert self.absence is not None
        offending = _select(events, self.absence)
        if offending:
            return QueryResult(
                outcome=QueryOutcome.UNSATISFIED,
                population=len(events),
                satisfied_count=0,
                coverage_ratio=0.0,
                violations=(
                    Violation(
                        reason=f"{len(offending)} event(s) matched an assertion of absence",
                        trace_ids=_trace_ids(offending),
                    ),
                ),
                reason=f"{len(offending)} prohibited event(s) found",
            )
        return QueryResult(
            outcome=QueryOutcome.SATISFIED,
            population=len(events),
            satisfied_count=len(events),
            coverage_ratio=1.0,
        )

    def _evaluate_coverage(self, events: Sequence[dict[str, Any]]) -> QueryResult:
        """The number an auditor actually asks for: what proportion is covered."""
        assert self.coverage is not None
        population_events = _select(events, self.coverage.get("of") or {})
        population = len(population_events)

        if population == 0:
            # Zero denominator. Reporting 100% here is the single most
            # dangerous thing this engine could do: a system that emitted no
            # risky calls at all would look perfectly governed.
            return QueryResult(
                outcome=QueryOutcome.INDETERMINATE,
                population=0,
                satisfied_count=0,
                coverage_ratio=None,
                reason=(
                    "no events matched the population this control is about, so "
                    "coverage is undefined — this is not a pass"
                ),
            )

        satisfied_by = self.coverage.get("satisfied_by") or {}
        min_ratio = float(self.coverage.get("min_ratio", 1.0))

        covered: list[dict[str, Any]] = []
        uncovered: list[dict[str, Any]] = []
        steps = satisfied_by.get("sequence") or []
        for candidate in population_events:
            if steps:
                ok = all(self._step_holds_for(candidate, step, events) for step in steps)
            else:
                ok = _matches(candidate, satisfied_by)
            (covered if ok else uncovered).append(candidate)

        ratio = len(covered) / population
        satisfied = ratio >= min_ratio
        violations: tuple[Violation, ...] = ()
        if uncovered:
            violations = (
                Violation(
                    reason=f"{len(uncovered)} of {population} events were not covered",
                    trace_ids=_trace_ids(uncovered),
                ),
            )
        return QueryResult(
            outcome=QueryOutcome.SATISFIED if satisfied else QueryOutcome.UNSATISFIED,
            population=population,
            satisfied_count=len(covered),
            coverage_ratio=ratio,
            violations=violations,
            reason=(
                None if satisfied else f"coverage {ratio:.1%} is below the required {min_ratio:.1%}"
            ),
        )

    def _evaluate_sequence(
        self, events: Sequence[dict[str, Any]], steps: list[dict[str, Any]]
    ) -> QueryResult:
        """Every event matching a step must have its required predecessor."""
        population = 0
        satisfied = 0
        failures: list[dict[str, Any]] = []

        for step in steps:
            targets = _select(events, step.get("match") or {})
            population += len(targets)
            for target in targets:
                if self._step_holds_for(target, step, events):
                    satisfied += 1
                else:
                    failures.append(target)

        if population == 0:
            return QueryResult(
                outcome=QueryOutcome.INDETERMINATE,
                population=0,
                satisfied_count=0,
                coverage_ratio=None,
                reason="no events matched the sequence's target, so nothing was assessed",
            )

        ratio = satisfied / population
        violations: tuple[Violation, ...] = ()
        if failures:
            violations = (
                Violation(
                    reason=f"{len(failures)} event(s) lacked the required preceding event",
                    trace_ids=_trace_ids(failures),
                ),
            )
        return QueryResult(
            outcome=QueryOutcome.SATISFIED if not failures else QueryOutcome.UNSATISFIED,
            population=population,
            satisfied_count=satisfied,
            coverage_ratio=ratio,
            violations=violations,
            reason=None
            if not failures
            else f"{len(failures)} event(s) were not preceded as required",
        )

    def _step_holds_for(
        self,
        target: dict[str, Any],
        step: dict[str, Any],
        events: Sequence[dict[str, Any]],
    ) -> bool:
        """Does `target` have the predecessor its step requires?"""
        preceding = step.get("requires_preceding")
        if not preceding:
            return True

        target_time = event_time(target)
        window = None
        if "within" in preceding:
            try:
                window = parse_duration(preceding["within"])
            except ValueError:
                # A malformed window is caught by validate(); refusing to hold
                # here means it cannot silently pass in the meantime.
                return False

        same_session = bool(preceding.get("same_session", True))
        spec = preceding.get("match") or {}

        for candidate in events:
            if candidate is target or not _matches(candidate, spec):
                continue
            if same_session and candidate.get("session_id") != target.get("session_id"):
                continue
            candidate_time = event_time(candidate)
            if target_time is None or candidate_time is None:
                # An untimed event cannot be placed before or after anything.
                # Accepting it would let a missing timestamp satisfy a
                # temporal control.
                continue
            if candidate_time > target_time:
                continue
            if window is not None and target_time - candidate_time > window:
                continue
            return True
        return False

    def _evaluate_resolution(self, events: Sequence[dict[str, Any]]) -> QueryResult:
        """Did escalations actually close, and inside the deadline?

        This is what Art. 14 asks and what a presence check cannot answer: an
        escalation nobody acted on is worse evidence than no escalation, because
        it shows the mechanism exists and is ignored.
        """
        assert self.resolution is not None
        opens = _select(events, self.resolution.get("opens_with") or {})
        if not opens:
            return QueryResult(
                outcome=QueryOutcome.INDETERMINATE,
                population=0,
                satisfied_count=0,
                coverage_ratio=None,
                reason="no opening events found, so resolution could not be assessed",
            )

        closes = _select(events, self.resolution.get("closes_with") or {})
        min_ratio = float(self.resolution.get("min_ratio", 1.0))
        window = None
        if "within" in self.resolution:
            try:
                window = parse_duration(self.resolution["within"])
            except ValueError:
                window = None

        resolved: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        for opener in opens:
            opened_at = event_time(opener)
            match_found = False
            for closer in closes:
                if closer.get("session_id") != opener.get("session_id"):
                    continue
                closed_at = event_time(closer)
                if opened_at is None or closed_at is None or closed_at < opened_at:
                    continue
                if window is not None and closed_at - opened_at > window:
                    continue
                match_found = True
                break
            (resolved if match_found else unresolved).append(opener)

        ratio = len(resolved) / len(opens)
        satisfied = ratio >= min_ratio
        violations: tuple[Violation, ...] = ()
        if unresolved:
            violations = (
                Violation(
                    reason=(
                        f"{len(unresolved)} escalation(s) were never resolved within "
                        "the required window"
                    ),
                    trace_ids=_trace_ids(unresolved),
                ),
            )
        return QueryResult(
            outcome=QueryOutcome.SATISFIED if satisfied else QueryOutcome.UNSATISFIED,
            population=len(opens),
            satisfied_count=len(resolved),
            coverage_ratio=ratio,
            violations=violations,
            reason=(
                None
                if satisfied
                else f"resolution rate {ratio:.1%} is below the required {min_ratio:.1%}"
            ),
        )


def assign_tier(
    result: QueryResult,
    *,
    declared: bool,
    integrity: IntegrityStatus,
    independently_confirmed: bool = False,
) -> AssuranceTier:
    """Map a query result to an assurance tier.

    The rules, and why each is drawn where it is:

    * A query that did not pass never rises above DECLARED, whatever the
      system asserts about itself.
    * EVIDENCED requires the deterministic query to pass over a non-empty
      population. A pass over zero events is not evidence of anything.
    * VERIFIED additionally requires the supporting events to sit in a chain
      that verifies **and** an independent confirmation — a re-verified content
      marking, or a recorded human attestation. Without the second condition,
      VERIFIED would mean "the system said so and the log was not edited",
      which is not independent of the party being assessed.
    """
    if result.outcome is QueryOutcome.INDETERMINATE:
        return AssuranceTier.DECLARED if declared else AssuranceTier.UNKNOWN
    if result.outcome is QueryOutcome.UNSATISFIED:
        return AssuranceTier.DECLARED if declared else AssuranceTier.UNKNOWN
    if result.population == 0:
        return AssuranceTier.DECLARED if declared else AssuranceTier.UNKNOWN
    if integrity is IntegrityStatus.FAILED:
        # A broken chain does not merely fail to strengthen the claim; it
        # undermines the evidence the claim rests on.
        return AssuranceTier.DECLARED if declared else AssuranceTier.UNKNOWN
    if integrity is IntegrityStatus.VERIFIED and independently_confirmed:
        return AssuranceTier.VERIFIED
    return AssuranceTier.EVIDENCED


@dataclass
class AssuranceReport:
    """Per-tier counts. Deliberately has no single blended score.

    Blending is how a field-presence check becomes a "92% compliant" headline.
    The CLI prints these three numbers and refuses to combine them (P10).
    """

    unknown: int = 0
    declared: int = 0
    evidenced: int = 0
    verified: int = 0
    indeterminate: int = 0

    @property
    def total(self) -> int:
        return self.unknown + self.declared + self.evidenced + self.verified

    def add(self, tier: AssuranceTier) -> None:
        setattr(self, str(tier), getattr(self, str(tier)) + 1)

    def count_at_least(self, floor: AssuranceTier) -> int:
        return sum(
            count
            for tier, count in (
                (AssuranceTier.UNKNOWN, self.unknown),
                (AssuranceTier.DECLARED, self.declared),
                (AssuranceTier.EVIDENCED, self.evidenced),
                (AssuranceTier.VERIFIED, self.verified),
            )
            if tier_at_least(tier, floor)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_controls": self.total,
            "unknown": self.unknown,
            "declared": self.declared,
            "evidenced": self.evidenced,
            "verified": self.verified,
            "indeterminate": self.indeterminate,
            "note": (
                "Reported per tier and never blended. A 'declared' control is an "
                "assertion by the party being assessed; only 'evidenced' and above "
                "rest on observed runtime behaviour. There is deliberately no "
                "single readiness percentage."
            ),
        }
