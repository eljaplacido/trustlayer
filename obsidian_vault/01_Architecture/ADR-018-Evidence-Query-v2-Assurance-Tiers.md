---
adr: 18
title: Evidence Query v2 and Assurance Tiers
date: 2026-08-02
status: accepted
accepted: 2026-08-07
---

# ADR-018 — Evidence Query v2 and Assurance Tiers

## Context

Phase 7 shipped `evidence_query` as `{event_types, payload_filters,
min_count}` (`compliance/schemas/control.schema.json:74-93`). It answers
"does an event of this shape exist at least N times?" That is a presence
check, and presence is not compliance:

- Art. 14 is not satisfied by the existence of one `HUMAN_ESCALATION`. It
  asks whether oversight is *effective* — whether escalations were
  actually resolved, by whom, and how fast. There is today no event that
  records an escalation's **outcome** at all.
- Art. 15 is not satisfied by the existence of a passing `POLICY_CHECK`.
  It asks whether *every* risky action was gated.
- An auditor asks "what proportion of the population is covered", not
  "did it happen once".

Two further defects are confirmed in the shipped code:

**G0 — the Art. 50 catalog is dead code.** `control.schema.json`
enumerates seven event types; `core-rs/src/schema.rs` has nine
(`DisclosureShown`, `ContentMarked` were added in Phase 7).
`EvidenceLinker.load_control_framework(article-50-v1.yaml)` therefore
raises `ValidationError: 'DISCLOSURE_SHOWN' is not one of [...]`
(reproduced 2026-08-02). It was never caught because the readiness scanner
uses hardcoded `art-50.x` checks and never loads that catalog. The spec
prose (`01-wire-format.md:77`, `02-event-types.md:6`) still says "seven".

**G4 — readiness conflates declaration with conformity.** The scanner is
largely file-existence and field-presence checks, which is why two
dogfooded projects both score 100%. Publishing that as "readiness" invites
a bad surprise in a real assessment.

## Decision

### 1. Reuse `MatchSpec`. Do not invent a second predicate language.

The policy engine already has a payload predicate language (ADR-008,
`spec/v0.1/04-policy-language.md`). Evidence queries adopt it verbatim for
their `where` clause.

One language means one implementation, one test suite, one thing for an
author to learn, and — the real prize — **policies and controls become
mutually expressible**. A control can reference the policy that enforces
it, and a gap can be remediated by emitting a policy rule from the same
predicate (ADR-020's code emitter depends on this).

### 2. Query v2 grammar

All additions are optional; v1 queries keep their exact meaning, so every
existing catalog stays valid.

```yaml
evidence_query:
  scope: session            # session | system | window   (default: system)
  window: 90d               # required when scope == window

  # --- v1, unchanged ---
  event_types: [TOOL_CALL]
  payload_filters: {result: PASS}     # deprecated alias for `where`
  min_count: 1

  # --- v2 ---
  where:                     # MatchSpec predicates (ADR-008)
    tool_name: {in: [payments.transfer, payments.refund]}

  sequence:                  # ordered temporal predicate
    - match: {event_type: TOOL_CALL, where: {tool_name: {eq: payments.transfer}}}
      requires_preceding:
        match: {event_type: POLICY_CHECK, where: {result: {eq: PASS}}}
        within: 5s
        same_session: true

  coverage:                  # the number auditors actually want
    of: {event_type: TOOL_CALL, where: {trust_tier: {eq: privileged}}}
    satisfied_by: {sequence: [...]}
    min_ratio: 0.99

  absence:                   # negative assertion
    match: {event_type: TOOL_CALL, where: {tool_name: {in: [restricted.*]}}}

  resolution:                # escalation closed the loop
    opens_with: {event_type: HUMAN_ESCALATION}
    closes_with: {event_type: HUMAN_DECISION}   # see ADR-019
    within: 24h
    min_ratio: 0.95
```

`payload_filters` is retained as a deprecated alias that lowers to
`where`, with a deprecation warning from the loader and a removal target
of v0.3.

### 3. Assurance tiers replace the satisfied boolean

`ControlEvidence.satisfied: bool` becomes:

```python
class AssuranceTier(StrEnum):
    UNKNOWN   = "unknown"    # not assessed
    DECLARED  = "declared"   # asserted in system.yaml or a document only
    EVIDENCED = "evidenced"  # a deterministic query over traces supports it
    VERIFIED  = "verified"   # evidenced + integrity-checked + independently confirmed
```

`VERIFIED` requires all three of: the query passed; the supporting events
lie in an integrity chain that verifies (ADR-017); and an independent
confirmation exists — a re-verified content marking (ADR-019), or a
recorded human attestation with an identity and a timestamp.

The result object carries the numbers, not just the tier:

```python
@dataclass(frozen=True, slots=True)
class ControlEvidence:
    control_id: str
    control_title: str
    assurance: AssuranceTier
    population: int              # events matching `coverage.of`
    satisfied_count: int
    coverage_ratio: float | None
    violations: tuple[Violation, ...]      # each cites trace_ids
    determination: Determination           # DETERMINISTIC | LLM_ASSISTED | HUMAN
    gap_reason: str | None
    integrity: IntegrityStatus             # VERIFIED | UNCHAINED | FAILED
```

**Scores are reported per tier and never blended.** The CLI prints three
numbers (declared / evidenced / verified) and refuses to emit a single
"readiness %". `--min-assurance evidenced` gates CI. This is P10 in
`docs/PHASE-8-DESIGN.md` made mechanical: an operator cannot accidentally
publish a field-presence score as a conformity claim.

A fourth deterministic outcome is added: `INDETERMINATE` — the query
cannot decide (no population, ambiguous, evidence outside retention).
Only `INDETERMINATE` controls are eligible for model assistance (ADR-020),
which is what keeps evaluator cost bounded and P2 enforceable.

### 4. Control metadata: role and applicability dates

```yaml
- id: art-50.2.1
  applies_to_roles: [provider]          # provider | deployer | importer | distributor
  applies_from: 2026-12-02              # Digital Omnibus deadline
  legal_ref: "Art. 50(2)"
  risk_classes: [limited-risk, high-risk]
```

The scanner filters by the system's `provider_role` and reports
not-yet-applicable controls separately with a countdown ("applies in 4
months"). This encodes the omnibus timeline as data rather than prose, so
the catalog stays correct as dates pass and a deployer is never scored
against provider obligations (G9).

### 5. Streaming evaluation

The engine streams via `GET /v1/events?after_seq=…` (ADR-017 §6) with
bounded memory. Filters push down to the store's existing `EventFilter`
(agent, session, event_type, limit). Sequence and coverage predicates
evaluate over a sliding window sized by the largest `within` in the query,
so memory is a function of the query, not of the store.

### 6. Fixing G0, permanently

- `control.schema.json` derives its event-type enum from the same source
  as the SDKs, and a test asserts the schema enum equals the Rust
  `EventType` variants.
- Spec prose "seven" → the actual count, in `01-wire-format.md` and
  `02-event-types.md`, with §2 sections for the Phase 7 types.
- A regression test loads **every** file in `compliance/controls/` through
  `EvidenceLinker.load_control_framework`. The bug survived because no
  test ever loaded that catalog; this closes the class, not the instance.
- §5.3 of the Phase 8 design extends the existing cross-language
  lockstep rule to cover compliance schemas.

## Consequences

- Existing catalogs keep working; v2 fields are additive and optional.
- `satisfied: bool` disappears from the report JSON. The dashboard
  `CompliancePane` and `report_generator` are updated in the same slice;
  the JSON gains a `schema_version` so consumers can branch.
- Reported readiness will **drop** for the two dogfooded projects once
  declaration and evidence are separated. That is the point, and the
  CHANGELOG says so plainly rather than presenting it as a regression.
- Authoring a v2 control is meaningfully harder than a v1 control. Two
  mitigations: the `evidence` skill documents the patterns, and ADR-020's
  NL→query compiler generates a candidate query that a human reviews —
  the query, never the answer.
- One predicate language means an ADR-008 change now has two consumers.
  The `spec` conformance suite is extended to cover predicate evaluation
  in the evidence engine, not just the policy engine.

## Implementation notes (2026-08-07)

Recorded rather than absorbed silently, in the same spirit as ADR-017 §7.

### The predicate operators are new, and they landed in both engines

§1 said "reuse `MatchSpec`. Do not invent a second predicate language." The
shipped `MatchSpec` only had dotted-path **deep equality**, so the `{in: […]}`
and `{eq: …}` forms this ADR's own §2 example uses did not exist anywhere. The
choice was to add them to one engine or to both.

Adding them only to the evidence side would have violated P6 on the very first
slice that invokes it, and would have recreated gap G0 one layer up: a control
asserting it is enforced by a policy rule, where the two match different sets
of events. So the operators landed in **both** — `core-rs/src/predicate.rs` and
`compliance/src/predicates.py` — behind one normative spec section (§4.3.1) and
one shared conformance table
(`spec/v0.1/fixtures/predicate-cases.json`), which both suites run.

Three decisions inside that:

- **Operators are `$`-prefixed and an object is an operator expression only
  when *every* key is prefixed.** Any other value keeps its v0.1 meaning, so no
  existing policy changes behaviour. A *mixed* object is rejected at load
  rather than compared literally: `{"$gt": 5, "unit": "ms"}` would otherwise
  become a predicate that can never match, and a rule that never fires is one
  nobody notices is broken until it fails to block something.
- **No regular-expression operator.** `$prefix`/`$suffix` cover the tool-family
  patterns catalogs actually need. A regex evaluated over a large event stream
  on behalf of a user-supplied catalog is a denial-of-service primitive, and
  the evidence engine is exactly where a catalog meets unbounded data.
- **Policies are validated at load, not at evaluation.** `Policy::from_json`
  now returns `Error::InvalidPolicyRule` for a malformed predicate. The guardian
  hot path stays a plain boolean.

### `VERIFIED` needs independent confirmation, and says so

§3 required "evidenced + integrity-checked + independently confirmed". The
implementation enforces all three, and the middle one asymmetrically: a
`FAILED` chain pulls a control **down** to `DECLARED` rather than merely
failing to raise it. A broken chain does not just withhold support, it
undermines the evidence the claim rests on.

Without the independent-confirmation condition, `VERIFIED` would mean "the
system said so and its log was not edited", which is not independent of the
party being assessed. That is stated in the code and in the tier's docstring so
it cannot be read as stronger than it is.

### The empty-population rule

`coverage` over a zero-size population returns `INDETERMINATE`, never a pass.
Reporting 100% there is the single most dangerous thing this engine could do: a
system that emitted no risky calls at all would look perfectly governed. The
same instinct puts a floor under the tiers — a satisfied query over an empty
population cannot reach `EVIDENCED`.

### Scope not yet built

- **Streaming evaluation (§5).** The engine still materialises the event list
  from `GET /v1/events`. `after_seq` exists on the store (ADR-017 §6) and is
  unused here. Correct at current volumes and a real limit at scale; the
  bounded-memory sliding window is deferred.
- **`scope` and `window`.** Present in the schema, not yet honoured by the
  evaluator — and therefore **rejected by `validate()`** rather than ignored. A
  query silently evaluated over a wider set than its author asked for produces
  a compliance answer to a question nobody posed, and the author has no way to
  tell. A loud error beats a quiet mismatch. Removing the rejection is the
  first step of implementing them.
