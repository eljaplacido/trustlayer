---
adr: 24
title: Remediation Guidance Engine — From Findings to Ordered Work
date: 2026-08-06
status: accepted
---

# ADR-024 — Remediation Guidance Engine

## Context

Phase 7 shipped a readiness scanner and an evidence linker. Both answer the
same shape of question — *is this control satisfied?* — and both stop there.
The output is a percentage.

Two problems follow from that, and both were observed while dogfooding.

**A score is not actionable.** "30% ready" tells a team nothing about what to
do next, so the work that actually happens is whatever is cheapest to make the
number move. That is the opposite of the intended incentive: the cheapest
checks to satisfy are field-presence checks, and satisfying those changes
nothing about the system.

**A score is not honest about what kind of work is missing.** Gap G4 recorded
that field-presence checks yield 100% scores. Underneath that is a subtler
failure: a compliance gap is closed in one of three dimensions — code,
documents, or recurring human activity — and closing it in the wrong one looks
identical in the scan. Writing an oversight policy does not create the
oversight process. Declaring a risk class in `system.yaml` does not make the
runtime enforce it. Both raise the score.

## Decision

Ship a remediation engine that turns findings into ordered, cited work.

### 1. Guidance is data, not code

Guidance lives in `compliance/remediation/<framework>.yaml`, validated against
`compliance/schemas/remediation.schema.json`. The planner
(`compliance/src/remediation.py`) contains no advice at all.

Two reasons, in priority order:

- **The regulation moves faster than the planner.** The Digital Omnibus
  re-cut the AI Act timeline in May 2026 without touching a line of anyone's
  code. Guidance that lives in Python requires an engineer for a change that is
  not an engineering change.
- **Guidance must be reviewable by the people who own it.** A compliance
  officer or counsel can review a YAML catalog. They will not review a module.
  Since the guidance is the substance of this feature, the format has to match
  the reviewer.

### 2. Three dimensions, named explicitly

Every entry declares `technical`, `documentation`, or `process`.

This is the load-bearing decision. It is the difference between a tool that
reports gaps and one that reports *the right kind of work*, and it is what
prevents the most common failure mode: satisfying a documentation check and
believing the underlying control now operates.

The rendered plan groups by dimension after the blocking section, because the
three dimensions are usually three different people. A plan that interleaves
them reads as one impossible task instead of three tractable ones.

### 3. Deterministic, per P2

The planner matches findings against the catalog. It does not generate advice.
The same findings always produce the same plan, byte for byte — which is what
makes a plan diffable, and therefore reviewable, across runs.

A model may later *explain* an item or draft prose for one (ADR-020). It never
invents one. The moment guidance is generated, a reviewer has to re-check every
item on every run instead of reviewing a diff.

### 4. Findings converge; items do not duplicate

Missing instrumentation makes every evidence-backed control unsatisfiable at
once. Emitting the same remediation per triggering finding would render a
single-cause plan as twenty separate problems and bury the one action that
resolves all of them.

Items are therefore keyed by guidance id and cite every finding that triggered
them. An item takes the severity of its **most severe** trigger — taking the
mildest would let one low-priority match mask a critical one.

### 5. Ordering: blocking, then priority, then effort

`(blocking, priority, effort, id)`.

Effort ascends *within* a priority tier rather than across it. Sorting quick
wins to the top globally optimises for the appearance of progress: a plan that
closes six cheap documentation gaps while instrumentation is still absent has
moved the score and not the system. `id` is the final key so the ordering is
total and the output is stable.

### 6. Unguided findings are reported, never dropped

A finding with no catalog entry appears in an `unguided` section of the plan
and in the summary count.

Silently returning a shorter plan is the worst available behaviour: it reads as
"little work remains", which is precisely inverted. This mirrors P3 — the
retention floor refuses to lose evidence, and the planner refuses to lose a
finding.

### 7. Propose, never apply (P4)

`artifacts` name files the work would create or change. Nothing is written.
This is an Art. 14 posture rather than an unimplemented feature, and it is
stated in the rendered output so a reader does not assume otherwise.

### 8. Every entry carries a basis, an owner, and a verification step

Enforced by tests over the shipped catalog, not by convention:

- `legal_basis` — a finding a reader cannot check is a finding they must trust.
- `owner_role` — the most common reason a gap stays open is that no role owned
  it.
- `verification` — guidance with no verification produces work nobody can
  confirm, which is indistinguishable from work not done.

A further test parses `readiness_scanner.py` for `check_id=` literals and fails
if any check has no guidance. A tool that reports a gap it cannot advise on is
half a feature, and the coverage would otherwise rot the first time a check was
added.

## Consequences

- `compliance/` gains `remediation/` and one module. No new dependency: the
  catalog is validated with the `jsonschema` already used for control and
  system schemas, and modelled with dataclasses like the rest of the package.
- The compliance package gains a mypy gate (`disallow_untyped_defs`,
  `disallow_any_generics`, `warn_return_any`, `no_implicit_optional`,
  `strict_equality`) per `docs/PHASE-8-DESIGN.md` §5.2. `scripts/verify.sh`
  passes `--config-file` explicitly, because mypy invoked from the repo root
  would otherwise find no config and run with defaults — a gate that is
  switched off without failing is worse than no gate.
- CI can gate on `--fail-on-blocking` and attach the plan as an artifact. A red
  build that says "30% ready" tells the next person nothing; the attached plan
  tells them which items block a claim and who owns each.
- **Catalog quality is now a maintenance obligation.** Guidance that drifts
  from the regulation is worse than absent guidance, because it will be
  followed. The catalog carries a `version` and a `jurisdiction` so a stale or
  misapplied catalog is at least visible.
- The engine reports what the Act's text requires and what TrustLayer can
  observe. Whether a measure is sufficient for a particular system remains a
  determination for the provider and their counsel, and the disclaimer is
  attached to every generated plan rather than living only in a README.

## Relation to other decisions

- Extends the Phase 7 scanner and linker (ADR-016) rather than replacing them;
  both feed `Finding` through one normalised shape.
- Slice 8.5 (ADR-021, Annex IV document model) will consume the same catalog to
  populate per-claim provenance — a remediation item and an Annex IV claim are
  the same fact at two lifecycle stages.
- Slice 8.2 (ADR-018, assurance tiers) will refine `Finding.status`: today
  `PARTIAL` and `MISSING` are derived from evidence counts, which is a
  presence check, and the tiers replace that with a graded assessment.
