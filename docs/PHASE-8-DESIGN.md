# Phase 8 — Compliance Depth, Agentic Trust, and the Evaluator Layer

**Status:** Design (proposed, not yet accepted)
**Date:** 2026-08-02
**Supersedes nothing. Extends:** Phase 7 (EU AI Act Compliance Framework)

This document is the master plan for Phase 8. It states the regulatory
context, the design principles every slice must honour, the engineering
contract (tests, typing, linting, docs, skills), and the slice sequencing.
Each architectural decision has its own ADR (ADR-017 … ADR-023); this
document is the map, the ADRs are the territory.

---

## 1. Regulatory context (as of 2026-08-02)

The Digital Omnibus on AI (political agreement 2026-05-06, Council
confirmation 2026-05-13, entry into force July 2026) re-cut the AI Act
timeline without softening the substance.

| Obligation | Applies from | Note |
|---|---|---|
| Art. 5 prohibitions; Art. 4 AI literacy | 2025-02-02 | live, untouched |
| GPAI model obligations | 2025-08-02 | live |
| Art. 50 disclosure (chatbot, emotion recognition, biometric categorisation, deepfake) | **2026-08-02** | live **today**, untouched |
| Art. 50(2) machine-readable marking of synthetic content | **2026-12-02** | deferred; 3-month grace for pre-Aug systems |
| Prohibited CSAM/nudifier technical safeguards | 2026-12-02 | new |
| High-risk, standalone (Annex III) | **2027-12-02** | deferred from 2026-08-02 |
| High-risk embedded in regulated products (Annex I) | 2028-08-02 | deferred |
| National regulatory sandboxes | 2027-08-02 | deferred |

Also material: registration stayed mandatory (the proposed exemption for
self-assessed non-high-risk systems was rejected, only a lighter
administrative footprint survived); a Machinery Regulation carve-out; AI
Office supervision extended to all systems built on a GPAI model from the
same undertaking; bias-detection data processing extended to all providers
and deployers.

**The strategic fact.** As of mid-2026 **no CEN-CENELEC JTC 21 harmonised
standard is cited in the OJEU**, so nothing yet confers the Art. 40
presumption of conformity. EN 18286 (QMS) is at formal vote; prEN 18228,
prEN 18229-1 and prEN 18282 are at Enquiry; the target is Q4 2026, with
CEN/CENELEC having authorised publication straight after a positive
Enquiry vote to hit it.

Two consequences shape Phase 8:

1. Without a presumption-of-conformity shortcut, compliance must be
   demonstrated **on evidence**. Runtime evidence is the scarce good.
2. The deferral to 2027-12-02 does not reduce the work — it means the
   evidence must cover a longer operating history by the time it is
   assessed. Evidence captured in 2026 is worth more in 2027 than any
   documentation product bought in late 2027.

TrustLayer's position is therefore: **be the evidence layer, and make the
evidence hard to doubt.**

### Annex IV (Art. 11) — what the documentation must contain

Nine sections: (1) general description; (2) development process incl.
third-party tools, design rationale, data provenance, human-oversight
measures, validation/testing with signed test reports, cybersecurity;
(3) monitoring, functioning and control incl. accuracy per population and
foreseeable unintended outcomes; (4) appropriateness of performance
metrics; (5) risk management system (Art. 9); (6) **lifecycle changes**;
(7) harmonised standards applied; (8) EU declaration of conformity;
(9) post-market monitoring plan (Art. 72). SMEs may supply this in
simplified form.

### Art. 12 read against agentic systems

Automatic logging over the system's lifetime covering risk-presenting
situations and substantial modification, post-market monitoring data, and
deployer operational monitoring — **tamper-evident**, retained ≥6 months
(24 for biometric / law enforcement), with Art. 18 pushing documentation
retention to 10 years. Commission guidance is explicit that agentic
workflows must log events relevant to risk identification, **not only
final outputs**.

---

## 2. Confirmed gaps in TrustLayer as of Phase 7

Each is verified against the code, not inferred.

| # | Gap | Evidence | ADR |
|---|---|---|---|
| G0 | **Art. 50 control catalog is dead code.** `control.schema.json` enumerates 7 event types; Rust `EventType` has 9. Loading `article-50-v1.yaml` raises `ValidationError` on `DISCLOSURE_SHOWN`. Tests pass only because the scanner uses hardcoded `art-50.x` checks. Spec §1.3/§2 still say "seven". | reproduced 2026-08-02 | 018 |
| G1 | **Retention is a count cap, not a time floor.** `events.rs::enforce_retention` evicts oldest events on overflow — can destroy logs Art. 12 requires for 6 months. | `core-rs/src/events.rs:184` | 017 |
| G2 | **No tamper-evidence.** No hash, signature, Merkle or chain construct anywhere in `core-rs/src`. | grep returns nothing | 017 |
| G3 | **Evidence queries are presence checks.** `{event_types, payload_filters, min_count}` cannot express "every risky call was preceded by a passing policy check". | `control.schema.json:74-93` | 018 |
| G4 | **Readiness conflates declaration with conformity.** Field-presence checks yield 100% scores. | `readiness_scanner.py` | 018 |
| G5 | **No Annex IV document model.** Audit generator emits summary Markdown with no per-claim provenance. | `audit_generator.py` | 021 |
| G6 | **No Art. 73 incident pipeline.** No incident record, no statutory clocks, no Commission template mapping. | absent | 022 |
| G7 | **No Art. 43 substantial-modification detection.** Nothing fingerprints the harness or diffs it across runs. | absent | 019 |
| G8 | **`CONTENT_MARKED` records a claim, not a fact.** No verification that the artifact carries a real marking. | `article-50-v1.yaml` | 019 |
| G9 | **Controls are not role-filtered.** `provider_role` exists in the system schema but no control carries `applies_to_roles`. | `system.schema.json` | 018 |
| G10 | **Agentic failure modes are not modelled.** No delegation depth, sub-agent spawning, goal drift, tool-privilege flow, or escalation *outcome*. | absent | 019 |
| G11 | ~~**No evaluator layer.** `llm_reflector.py` is the right pattern but is Hermes-private and single-purpose.~~ **Closed 2026-08-16** by `evaluators/`; `llm_reflector.py` now calls it. | `skills/hermes/llm_reflector.py` | 020 |

---

## 3. Design principles

These are binding on every slice. A change that violates one needs an ADR
that says so explicitly.

**P1 — Evidence-cited or it didn't happen.** Every machine-generated
assertion carries cited `trace_id`s or `file:line`. Citations are
validated against the evidence window at the schema boundary; ungrounded
findings are rejected, not softened. A compliance package containing one
fabricated citation is worse than no package — an auditor who finds it
discards everything else.

**P2 — Deterministic first, model second.** The deterministic engine
decides everything it can. A model is invoked only on what the engine
marked `INDETERMINATE`, and its output is re-checked deterministically
wherever a check exists. Models never replace a computable answer.

**P3 — Never silently lose evidence.** Overflow archives, it does not
delete. A retention floor refuses eviction. Failures are loud and
metered.

**P4 — Propose, never apply.** No component writes to a user's repo,
vault, or registry on its own authority. Everything is a reviewable
proposal with a diff; a human accepts. This is an Art. 14 obligation, not
a UX preference.

**P5 — Additive to the wire.** The v0.1 envelope is a shipped contract
across four SDKs. Prefer new optional fields, new event types, and new
routes (all MINOR per spec §1.7) over reshaping what exists. Anything
that can live server-side stays out of the envelope.

**P6 — One predicate language.** Controls and policies speak the same
dialect. Evidence queries reuse the `MatchSpec` payload predicates from
ADR-008 rather than inventing a second language.

**P7 — Data minimisation by default.** Traces carry prompts, responses
and potentially personal data. Evidence leaves the process only under an
explicit egress policy, redacted by default. Sending a system's traces to
a third-country endpoint to assess its GDPR posture is self-defeating.

**P8 — Dogfood.** The evaluator layer emits `AgentTraceEvent`s and passes
through Guardian like any other agent. TrustLayer's own AI use is
evidence in TrustLayer.

**P9 — Instrumentation never takes down the host.** Unchanged from Phase
2 and still absolute for SDK paths. Note the deliberate asymmetry: the
*store* may refuse a write to protect evidence integrity (P3); the *SDK*
may not.

**P10 — Honest naming.** A heuristic is called a heuristic. Assurance
tiers are never blended into one number. "Readiness" never masquerades as
"conformity".

---

## 4. Architecture delta

```
                      ┌──────────────────────────────────────┐
                      │  agentic client (Claude Code /       │
                      │  OpenCode) — the WRITE path          │
                      └───────────────┬──────────────────────┘
                                      │ MCP: list/apply proposal
                      ┌───────────────▼──────────────────────┐
   dashboard  ───────▶│  mcp-server  (Phase 5, extended)     │
   (READ lens)        └───────────────┬──────────────────────┘
        │                             │
        │                 ┌───────────▼───────────┐
        │                 │  evaluators/          │  NEW — ADR-020
        │                 │  trustlayer_eval      │
        │                 │  · providers (BYO)    │
        │                 │  · 6 evaluator roles  │
        │                 │  · grounding validator│
        │                 │  · egress policy      │
        │                 └───────────┬───────────┘
        │                             │
        │                 ┌───────────▼───────────┐
        │                 │  compliance/          │  EXTENDED
        │                 │  · evidence engine v2 │  ADR-018
        │                 │  · agentic trust      │  ADR-019
        │                 │  · annex_iv/          │  ADR-021
        │                 │  · incidents/         │  ADR-022
        │                 └───────────┬───────────┘
        │                             │ GET /v1/events?after_seq=…
        └─────────────────────────────┼──────────────────────────
                          ┌───────────▼───────────┐
                          │  core-rs guardian     │  EXTENDED
                          │  · TraceStore         │  ADR-017
                          │  · integrity chain    │
                          │  · retention floor    │
                          └───────────────────────┘
```

New top-level directory: `evaluators/`, laid out exactly like
`compliance/` (`src/`, `tests/`, `pyproject.toml`,
`requirements-release.txt`) so it slots into `scripts/verify.sh` as one
more block.

---

## 5. Engineering contract

Non-negotiable for every slice. This section is what "designed with best
practices" means concretely in this repo.

### 5.1 Language gates

| Layer | Gate |
|---|---|
| Rust | `cargo fmt --all -- --check`; `cargo clippy --features server --all-targets -- -D warnings`; no `unwrap()`/`expect()` on production paths (test code exempt); `cargo test --features server` |
| Python | `ruff format --check`; `ruff check`; `mypy` strict on the package; `from __future__ import annotations` in every module; Pydantic v2 for anything crossing a boundary |
| TypeScript | `tsc --noEmit` under `strict` + `noUncheckedIndexedAccess`; `vitest run`; `vite build` |
| Go | `go vet ./...`; `go test ./... -count=1 -race`; stdlib + `google/uuid` only |

`scripts/verify.sh` gains an `evaluators` block mirroring the
`compliance` block, and a new `./scripts/verify.sh evaluators` mode. CI
gains the matching job. **A slice is not done until `./scripts/verify.sh
test` exits 0.**

### 5.2 Typing rules

- Python: mypy strict for `compliance.src` and `trustlayer_eval`. New
  code adds `disallow_untyped_defs`, `disallow_any_generics`,
  `warn_return_any`, `no_implicit_optional`. Provider responses are
  parsed into Pydantic models at the boundary — `dict[str, Any]` never
  escapes a provider module.
- Rust: newtypes for hashes and sequence numbers (`EventHash`,
  `Seq`) rather than bare `String`/`u64`, so a chain hash cannot be
  swapped for a content hash by mistake.
- TypeScript: discriminated unions for `Proposal`, `AssuranceTier` and
  evaluator verdicts. No `any`; `unknown` + a parse function at the fetch
  boundary.

### 5.3 Test strategy per layer

- **Rust (integrity):** table-driven unit tests for append, verify,
  tamper-detection (mutate a byte mid-log → verification fails at the
  right seq), crash recovery (truncated chain tail), retention floor
  (young events are not evictable), archive-on-overflow. Plus a
  randomised invariant loop over interleaved appends and verifies. No new
  test dependency.
- **Python (evaluators):** every provider is exercised through
  `httpx.MockTransport` — **no test touches the network**, matching the
  pattern already established in `skills/hermes/tests/test_llm_reflector.py`.
  Grounding validation gets adversarial fixtures: fabricated `trace_id`s,
  ids from outside the window, empty citation lists, duplicate ids.
- **Python (documents):** golden-file tests. Generated Annex IV Markdown
  and JSON are byte-compared against committed goldens so any drift is a
  visible diff, and so regeneration is provably stable (a stable ordering
  is what makes lifecycle-change diffs meaningful — see ADR-021).
- **TypeScript (workbench):** testing-library with `user-event`, including
  keyboard-only navigation of the proposal diff and `aria-live`
  assertions on evaluator output. Status badges are asserted to carry
  text, not colour alone.
- **Cross-language conformance:** every new event type ships a fixture in
  `spec/v0.1/fixtures/` and a round-trip test in **all four** SDKs plus
  `core-rs`, in the same commit. G0 exists precisely because this rule
  was not applied to the `control.schema.json` enum — the rule is hereby
  extended to cover compliance schemas.

### 5.4 Documentation obligations

Every slice that touches a contract updates, in the same commit:
`spec/v0.1/` (normative) → `docs/SCHEMA.md` (mirror) → SDK docs →
`compliance/README.md` / new module README → `docs/CURRENT_STATUS.md` →
`CHANGELOG.md`. ADRs are dated and append-only; a superseded decision
gets a new ADR, never an edit.

### 5.5 Agentic skill alignment

Agent-facing skills are part of the deliverable, not an afterthought —
they are how the next agent session stays inside the design.

- Canonical skills live in `.opencode/skills/<name>/SKILL.md`.
- `.claude/skills/<name>` becomes a **symlink** to the canonical
  directory so Claude Code and OpenCode read one source of truth and
  cannot drift. (Decision recorded in ADR-023 §7.)
- New skills: `evidence` (authoring and reviewing evidence queries),
  `evaluators` (adding a provider or an evaluator role, and the grounding
  contract), `workbench` (dashboard component and a11y conventions).
- `compliance` SKILL.md is extended with the assurance-tier vocabulary
  and the "propose, never apply" rule.
- Every skill states its **refusal conditions** — e.g. the `evaluators`
  skill must refuse to emit a finding without citations, and the
  `compliance` skill must refuse to present output as legal advice or
  certification.

### 5.6 Performance budget

- Chain append: ≤ 50 µs added per event (one SHA-256 over a canonical
  serialisation already being produced for the JSONL write).
- Evidence query over 1M events: streamed with `after_seq` pagination,
  bounded memory, no full materialisation in Python.
- Evaluator cost: the control judge sees only `INDETERMINATE` controls.
  Expected model calls per full scan are documented and asserted in a
  test so a regression that fans out to every control is caught.

---

## 6. Slice sequencing

Ordered by dependency and by regulatory urgency (Art. 50(2) marking lands
2026-12-02; high-risk 2027-12-02).

| Slice | Status | Content | ADR | Depends on |
|---|---|---|---|---|
| **8.0** | **shipped** | Fix G0: event-type enum drift across `control.schema.json`, spec §1.3/§2 ("seven" → nine), fixtures, cross-SDK round-trip tests. Regression test that loads **every** catalog in `compliance/controls/`. | 018 | — |
| **8.1** | **shipped** *(Postgres parity deferred)* | Evidence integrity: per-`agent_id` hash chain, signed checkpoints, `GET /v1/integrity/*`, time-based retention floor, archive-on-overflow. | 017 | 8.0 |
| — | **shipped** | Remediation guidance engine. Unplanned; came out of dogfooding 8.0. | 024 | 8.0 |
| **8.2** | **shipped** *(streaming deferred)* | Evidence query v2: MatchSpec reuse, sequence/coverage/absence/resolution predicates, assurance tiers, role and date filtering, `after_seq` pagination. | 018 | 8.1 |
| **8.3** | **partial** | Agentic trust model. Shipped: `HARNESS_SNAPSHOT` + `HUMAN_DECISION` event types, optional `parent_trace_id`. Open: workflow graph metrics, trust envelope, substantial-modification change records, marking verification. | 019 | 8.2 |
| **8.4** | **shipped** | `evaluators/` package: provider abstraction (null/ollama/agentcenter/openai-compatible/anthropic), egress policy, redaction, grounding validator, `EvaluatorRun` records, all six roles plus an operator-facing `insight_advisor`, and the dashboard Advisor pane. Hermes `LLMReflector` refactored onto it with its ADR-013 API and tests unchanged. | 020 | 8.2 |
| **8.5** | not started | Annex IV document model, per-claim provenance, Art. 13 / Art. 72 / Art. 47 generators, ISO 42001 + NIST AI RMF crosswalks, document author + code emitter roles. | 021 | 8.4 |
| **8.6** | not started | Art. 73 incident pipeline with statutory clocks and Commission template export. | 022 | 8.3, 8.5 |
| **8.7** | not started | Agentic workbench UIX: design tokens, hash routing, proposal diff, run cards, egress/assurance badges, NL→query compiler, MCP proposal tools. | 023 | 8.4, 8.5 |

Status is maintained here **and** in `docs/CURRENT_STATUS.md`; the latter
carries the detail and the stated limits. Deferrals are named in the row
rather than left to be discovered from the code.

Explicitly **out of scope for Phase 8**, recorded so it is not
accidentally absorbed:

- Runtime (in-line) trust-envelope enforcement in Guardian — needs
  session-scoped accumulator state; Phase 9.
- Merkle inclusion proofs for individual events — chain replay suffices
  at current volumes; Phase 9.
- A write-capable web service for the dashboard — the MCP path covers it;
  revisit only if non-MCP users demand it.
- Live token streaming into the workbench — Phase 8 polls run records.

---

## 7. Honest limits

Stated here so they appear in the product, not only in review.

1. **Causal-proximity taint is a heuristic.** Untrusted-to-privileged
   flow detection approximates data flow from causal adjacency. It
   produces findings for review, never proofs.
2. **"Substantial modification" is a legal determination.** TrustLayer
   detects and classifies *changes*; a human decides whether a change is
   substantial under Art. 43.
3. **"Serious incident" is a legal determination.** The pipeline computes
   deadlines and drafts reports; the classification is a required human
   field.
4. **Readiness ≠ conformity.** No output of this platform confers
   presumption of conformity. Until harmonised standards are cited in the
   OJEU, nothing does.
5. **Model-assisted findings are advisory.** Every one carries citations,
   a confidence, and a human-review flag, and none is presented as
   approved until a human has approved it.

---

## 8. ADR index

| ADR | Title |
|---|---|
| ADR-017 | Art. 12 Evidence Integrity — Hash-Chained Log and Retention Floor |
| ADR-018 | Evidence Query v2 and Assurance Tiers |
| ADR-019 | Agentic Trust Model — Harness, Workflow, Envelope |
| ADR-020 | `trustlayer-eval` — Pluggable Evaluator Providers with Grounded Output |
| ADR-021 | Annex IV Document Model and Claim Provenance |
| ADR-022 | Art. 73 Incident Pipeline |
| ADR-023 | Agentic Workbench UIX |
| ADR-024 | Remediation Guidance Engine — From Findings to Ordered Work |

ADR-024 was not in the original plan. It came out of dogfooding slice 8.0:
the scanner reported gaps and said nothing about closing them, so the work
that actually happened was whatever moved the score. Recorded here rather
than folded silently into 8.5.
