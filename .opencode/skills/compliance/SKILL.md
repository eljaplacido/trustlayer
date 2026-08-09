---
name: compliance
description: Use when working on TrustLayer EU AI Act / governance compliance tooling, system registries, readiness scans, evidence linking, audit packages, or Article 50 event types.
---

# Compliance Workflow

## Scope

- `compliance/` schemas, controls, scanner, evidence linker, evidence query,
  remediation planner, report/audit generators
- `compliance/remediation/` guidance catalogs
- Payload predicates — **both** `core-rs/src/predicate.rs` and
  `compliance/src/predicates.py` (see rule 6)
- Evidence-integrity surfaces (`core-rs/src/integrity.rs`, `checkpoint.rs`,
  `spec/v0.1/05-http-api.md` §5.12) when compliance tooling consumes them
- Dashboard Compliance pane consumers of readiness JSON
- Cross-SDK event types used as evidence (`DISCLOSURE_SHOWN`, `CONTENT_MARKED`,
  `HUMAN_DECISION`, `HARNESS_SNAPSHOT`)
- Hermes `07_Compliance/` graph notes when vault integration changes

## Rules

1. Read `docs/PROJECT.md`, `docs/CURRENT_STATE.md`, `compliance/README.md`,
   ADR-016, and — for Phase 8 work — `docs/PHASE-8-DESIGN.md` before editing.
2. Treat `compliance/schemas/*.schema.json` and `spec/` as normative. Do not
   invent flat `article_50` fields; use nested `disclosure_config` /
   `marking_config` as in `compliance/examples/system.yaml`.
3. Compliance output is evidence support, not legal advice or certification.
4. Never commit third-party system registries, live traces, tokens, or private
   audit packages.
5. Wire-contract event type changes must land together in Python, TypeScript,
   Go, Rust, cross-language tests, and control `evidence_query` definitions.
   Fixtures under `spec/v0.1/fixtures/` are read by all five implementations —
   a fixture exercised only by the language that produced it proves nothing
   about interoperability, and that omission is what produced gap G0.
6. **One predicate language, two implementations** (P6). Payload predicates
   live in `core-rs/src/predicate.rs` **and** `compliance/src/predicates.py`.
   They are a matched pair: the policy engine and the evidence engine must
   match the same events, or a control can claim to be enforced by a rule that
   does not. **Change one, change both, in the same commit**, and add a case to
   `spec/v0.1/fixtures/predicate-cases.json` — the shared table both suites
   run. Normative definition: spec §4.3 and §4.3.1.
   - Operators are `$`-prefixed. An object is an operator expression only when
     *every* key is prefixed; anything else is a literal compared by deep
     equality, so v0.1 policies keep their meaning.
   - There is deliberately **no regex operator**. A regex over a large event
     stream on behalf of a user-supplied catalog is a denial-of-service
     primitive. Use `$prefix` / `$suffix`.
7. **Deterministic first, model second** (P2). The engine decides everything it
   can compute. A model is invoked only on what the engine marked
   `INDETERMINATE`, and its output is re-checked deterministically wherever a
   check exists. Never replace a computable answer with a generated one.
8. **Propose, never apply** (P4). No compliance component writes to a user's
   repository, vault, or registry on its own authority. Remediation
   `artifacts` are suggested paths for a human to review. This is an Art. 14
   obligation, not a UX preference.
9. **Honest naming** (P10). A heuristic is called a heuristic. "Readiness"
   never masquerades as "conformity". Never blend assurance levels into a
   single number.

## Vocabulary

Use these words precisely; they are not interchangeable.

| Term | Means |
|---|---|
| **Readiness** | Declared fields and artifacts are present. Says nothing about whether they are true or operating. |
| **Evidence** | Runtime trace events substantiate a control. |
| **Verified** | Evidence exists, its integrity chain checks out, **and** something independent confirms it. See below — two of the three is `evidenced`, not `verified`. |
| **Conformity** | A legal status. TrustLayer never confers it, and as of 2026 no harmonised standard is cited in the OJEU, so nothing does. |
| **Blocking** | The gap defeats a conformity claim outright, rather than weakening it. |
| **INDETERMINATE** | The engine could not decide — empty population, no query, evidence outside retention. Distinct from a failure, and the *only* input a model layer may see (P2). |

Assurance tiers are `unknown` → `declared` → `evidenced` → `verified`. Never
blend them into one number; `AssuranceReport` deliberately has no combined
score, and reintroducing one recreates gap G4.

`verified` requires three things, not two: the query passed, the chain
verifies, **and** an independent confirmation. Without the third it would mean
"the system said so and its log was not edited", which is not independent of
the party being assessed. A *failed* chain pulls a control **down** to
`declared` — a broken chain undermines the evidence, it does not merely fail to
support it.

`PASS` on a readiness check means a field is filled in. Do not report it as
compliance.

## Refusal conditions

Refuse, and say why, when asked to:

- present compliance output as legal advice, certification, or a conformity
  claim;
- emit a finding, remediation item, or audit assertion without a citation to
  the check, control, or `trace_id` that produced it;
- write a generated artifact directly into a user's repository or registry
  rather than proposing it;
- raise a readiness score by loosening a check rather than closing the gap;
- silently drop a finding that has no authored guidance — report it as
  `unguided` instead;
- lower `TRUSTLAYER_RETENTION_MIN_DAYS` to resolve a disk-pressure alert. That
  alert means the store is refusing to destroy evidence; the fix is storage.

## Remediation guidance

`compliance/remediation/<framework>.yaml` holds the guidance catalog;
`compliance/src/remediation.py` matches findings against it. Guidance is
**data, not code** so it can be reviewed by someone who does not read Python
and updated when the regulation moves.

When authoring a catalog entry:

- Pick the **dimension** honestly — `technical`, `documentation`, or
  `process`. The most common way a gap is closed without being closed is
  fixing it in the wrong one: writing an oversight policy does not create the
  oversight process.
- Cite a `legal_basis`. A finding a reader cannot check is one they must trust.
- Give a `verification` step, ideally a command or an evidence query. Guidance
  with no verification produces work nobody can confirm.
- Name an `owner_role`. The most common reason a gap stays open is that no
  role owned it.
- Every check the scanner can emit must be covered; `test_remediation.py`
  enforces this by parsing `readiness_scanner.py` for `check_id=` literals.

## Standard Commands

```bash
# Focused compliance tests
./scripts/verify.sh compliance
# or
make compliance

# Full local gate (includes compliance lint + tests)
./scripts/verify.sh test

# Readiness scan against a project that has system.yaml
python -m compliance.src.readiness_scanner --project-dir /path/to/project \
    --output readiness.json

# Turn findings into an ordered remediation plan (never writes to the project)
python -m compliance.src.remediation --readiness readiness.json \
    --format markdown --output remediation.md

# CI gate: non-zero while blocking gaps remain
python -m compliance.src.remediation --readiness readiness.json \
    --fail-on-blocking

# Verify the evidence behind a compliance claim
curl "$GUARDIAN/v1/integrity/verify?agent_id=<id>"
curl "$GUARDIAN/v1/integrity/checkpoints?agent_id=<id>"

# Gate on runtime evidence rather than on declarations
python -m compliance.src.evidence_linker \
    --system system.yaml --framework compliance/controls/eu-ai-act-v1.yaml \
    --min-assurance evidenced
```

## Change Checklist

1. Update schema and example YAML together.
2. Update scanner / linker / generators and their tests.
3. **Add remediation guidance for any new check or control.** A gap the tool
   reports but cannot advise on is half a feature; the test suite fails if a
   `check_id` has no catalog entry.
4. If event types change, update all SDKs + `core-rs` + cross-language tests +
   a fixture in `spec/v0.1/fixtures/`.
5. Run `./scripts/verify.sh compliance` and, for release-path work,
   `./scripts/verify.sh test`.
6. Update `docs/CURRENT_STATE.md` / `docs/CURRENT_STATUS.md` when milestone
   status changes; add an ADR for architecture decisions.
