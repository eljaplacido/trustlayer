---
adr: 21
title: Annex IV Document Model and Claim Provenance
date: 2026-08-02
status: proposed
---

# ADR-021 — Annex IV Document Model and Claim Provenance

## Context

Art. 11 requires technical documentation drawn up **before** a high-risk
system is placed on the market and **kept up to date**, structured per
Annex IV's nine sections. Art. 13 requires instructions for use, Art. 47
an EU declaration of conformity, Art. 72 a post-market monitoring plan.

`compliance/src/audit_generator.py` emits a summary Markdown package. It
is a report *about* readiness, not the documentation the regulation asks
for, and — decisively — it carries no provenance: a reader cannot tell
which claim rests on which evidence, who wrote it, whether a human
approved it, or when it was last true (G5).

"Kept up to date" is the requirement that most shapes this design. A
document that is regenerated wholesale each time cannot show *what
changed*, yet Annex IV §6 asks precisely for changes through the
lifecycle.

## Decision

### 1. The document is a graph of claims, not a blob of prose

`compliance/schemas/annex_iv.schema.json` defines nine sections, each
holding claims:

```json
{
  "id": "s2g.validation-procedures",
  "section": "2g",
  "text": "Every privileged tool invocation was gated by a passing policy check.",
  "sources": [
    {"kind": "trace_query", "control_id": "art-15.2",
     "query_hash": "sha256:…", "result_hash": "sha256:…",
     "seq_range": [1, 41288], "coverage_ratio": 0.994,
     "integrity": "verified"},
    {"kind": "file", "path": "policies/default.json", "content_hash": "sha256:…"}
  ],
  "assurance": "verified",
  "authored_by": {"kind": "llm", "provider": "ollama",
                  "model": "nemotron-3-super:120b", "run_id": "…"},
  "approved_by": null,
  "approved_at": null,
  "last_verified": "2026-08-02T09:00:00+00:00"
}
```

Source kinds: `trace_query`, `file`, `document`, `human_attestation`.
Every claim inherits ADR-018's assurance tier from its weakest source, and
a claim with no source cannot exceed `DECLARED`.

Pinning `query_hash` **and** `result_hash` **and** `seq_range` is what
makes a claim re-checkable later: the log grows, but the exact evidence a
claim was made on stays identified.

### 2. Regeneration is stable, so diffs are meaningful

Claim ordering, id derivation, and serialisation are deterministic, so
regenerating an unchanged system produces a byte-identical document.
`git diff` on the generated Annex IV then shows exactly what changed
between two points in the lifecycle — which is Annex IV §6 satisfied as a
by-product of the build rather than as a separate manual exercise.

Golden-file tests enforce this: any nondeterminism in ordering shows up as
a failing byte comparison, not as a subtle drift discovered during an
audit.

### 3. AI authorship is marked, and approval is never implied

`authored_by.kind ∈ {human, deterministic, llm}`. Any claim with
`authored_by.kind == "llm"` and `approved_by == null` is:

- rendered with a visible unapproved marker in Markdown and in the
  workbench,
- excluded from any exported package built with `--require-approval`,
  which exits non-zero and names the unapproved claims,
- never counted toward an assurance tier above `DECLARED`.

There is no flag that auto-approves. Approval requires an identity and a
timestamp, recorded as a `human_attestation` source. Under Art. 14 a human
signs off; the tool's job is to make that signature structurally
necessary rather than culturally expected (P4).

### 4. Generated artifacts

| Artifact | Basis |
|---|---|
| `annex-iv.md` / `.json` | Art. 11 + Annex IV, nine sections |
| `instructions-for-use.md` | Art. 13 |
| `post-market-monitoring-plan.md` | Art. 72 |
| `declaration-of-conformity.md` | Art. 47 skeleton |
| `fria-draft.md` | Art. 27 fundamental rights impact assessment |
| `change-log.md` | Annex IV §6, from ADR-019 change records |

The Art. 47 declaration is a **skeleton** and is labelled as one. Signing
a declaration of conformity is an act with legal consequence; the platform
assembles the facts and refuses to present a completed declaration.

### 5. Crosswalks

`compliance/crosswalks/{iso-42001,nist-ai-rmf}.yaml` map TrustLayer
control ids to external framework ids, so one evidence base answers
several frameworks. Structure anticipates `en-18286.yaml` (QMS) once it
is cited in the OJEU — a slot, not a guess at its content.

Crosswalks are many-to-many and carry a `strength` field
(`equivalent | partial | related`). A `partial` mapping never transfers an
assurance tier; it transfers the evidence and re-evaluates. Overstating
crosswalk strength is the standard failure mode of compliance mapping
tools and the schema is built to make it visible.

### 6. Where documents live

Generated into the target project (not the TrustLayer repo) under
`compliance-artifacts/`, and mirrored into the Obsidian vault at
`07_Compliance/` by Hermes with wikilinks from claims to controls to
evidence. The vault is the human-navigable view; the JSON is the machine
contract.

Generation is a **proposal** when it would overwrite a file containing
human-approved claims: the generator writes a diff and refuses to clobber
an approval (P4).

## Consequences

- `audit_generator.py` is superseded for technical documentation but kept
  for the readiness summary, which remains a useful and distinct artifact.
  The distinction is named in `compliance/README.md`: readiness summary =
  where you stand; Annex IV package = what you file.
- Byte-stable generation is a hard constraint on every future generator
  change; the golden tests will fail loudly if it is broken, which is the
  intent.
- Documents will contain visibly unapproved claims for as long as nobody
  approves them. This is not a defect to design around.
- The `document_author` evaluator role (ADR-020) writes claim *text*
  only. It never writes `sources`, `assurance`, or `approved_by` —
  those come from the deterministic engine and from humans. A model
  cannot cite itself into a higher assurance tier.
- **Limits stated in-product:** a complete Annex IV package is not a
  conformity assessment and confers no presumption of conformity. Until
  harmonised standards are cited in the OJEU, nothing does.
