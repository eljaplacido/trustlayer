---
adr: 010
status: accepted
date: 2026-05-25
tags: [architecture, phase-6, spec, governance, open-standard]
supersedes: []
extends: ["[[ADR-008-MatchSpec-Payload-Predicates]]"]
---

# ADR-010 — Formal spec layout under `spec/v0.1/`

## Context

The production-readiness audit (Slice 4 item) flagged that
`docs/SCHEMA.md` "is good but reads as developer docs, not a formal
protocol spec. An open standard needs a versioned RFC-style
specification."

That's a real gap. `docs/SCHEMA.md` is the reference implementations'
mirror: it changes whenever the implementations change, it uses
imperative voice ("the SDKs serialise to the same shape"), and it does
not separate normative requirements from incidental advice. A
third party implementing the protocol cannot point at a stable URL and
say "we conform to *this version* of TrustLayer."

We need a citable artifact:
- frozen at the version label,
- written with explicit normative language,
- decoupled from any one implementation,
- structured so an outside contributor can see exactly what is
  required vs recommended vs informational.

## Decision

A new top-level `spec/` directory, with version-pinned subdirectories.
`spec/v0.1/` ships immediately; future wire-format major bumps get a
new `spec/v1.0/`, etc.

### Layout

```
spec/
├── README.md               Index for the whole spec tree.
└── v0.1/
    ├── README.md           Frontmatter, status, navigation, change log.
    ├── 01-wire-format.md   `AgentTraceEvent` envelope, types, normative JSON shape.
    ├── 02-event-types.md   The seven `event_type` values, per-type payload contract.
    ├── 03-cynefin.md       `CynefinDomain` enum semantics.
    ├── 04-policy-language.md  CSL: `Policy`, `PolicyRule`, `MatchSpec`, payload predicates.
    ├── 05-http-api.md      Guardian + trace-store HTTP contract; auth; metrics; rate-limit.
    └── 06-conformance.md   What an implementation MUST do to claim "TrustLayer v0.1".
```

### Normative language

We adopt **RFC 2119 / RFC 8174 keywords** (MUST, SHOULD, MAY, MUST
NOT, etc.) and follow the convention that they appear in ALL CAPS only
when they carry the normative meaning. Spec readers who already know
RFC 2119 don't need a primer; spec readers who don't have one in their
first reading of `spec/v0.1/01-wire-format.md`.

Each document carries one of three section markers:

- **Normative.** Implementations MUST follow the section.
- **Informative.** Background, rationale, examples — no conformance
  weight.
- **Examples.** Non-normative payloads / wire snippets. The Rust + Python +
  TypeScript SDK round-trip tests already cover the implementation-mirror
  side; the spec's examples exist only to make the prose readable.

### Versioning

`SCHEMA_VERSION` already lives in `docs/SCHEMA.md` (Slice 2 set it to
`0.2`). The spec is the **authoritative source** of that constant; the
implementation mirror cites the spec rather than the other way around.
The relationship is:

- `spec/v0.1/` is frozen at `SCHEMA_VERSION = 0.1`.
- Wire-format MINOR bumps add (in the same major) a new directory
  `spec/v0.2/` whose `01-wire-format.md` includes a section flagging
  the diff from `v0.1/`. Old directories are not edited after the
  bump — they are the citable artifact for clients who pin against
  that version.
- Wire-format MAJOR bumps open `spec/v1.0/`.
- Editorial fixes (typos, broken cross-links) within a frozen
  directory are PATCH-level changes to the spec and recorded in that
  directory's `README.md` change log. They MUST NOT change the
  meaning of any normative requirement.

### Relationship to existing docs

- `docs/SCHEMA.md` stays. It becomes the *implementation mirror*:
  developer-friendly, tightly linked to the SDK code paths. A banner
  at the top points at `spec/v0.1/` as the citable source of truth.
- `docs/VERSIONING.md` stays. Its "wire-format version" section
  defers to the spec's normative `SCHEMA_VERSION` declaration.
- `obsidian_vault/01_Architecture/ADR-*.md` stays. ADRs are
  decision records; the spec is the requirements record. They link
  to each other but never overlap.

### Conformance

`spec/v0.1/06-conformance.md` lists the discrete capabilities an
implementation must demonstrate to claim "TrustLayer v0.1 compliant",
grouped by feature surface (wire format, policy engine, HTTP API). A
language-agnostic conformance test fixture set is a follow-up — the
existing cross-language test (`core-rs/tests/cross_language.rs`)
already proves that the *reference* implementations agree on the
envelope shape, but it is not yet packaged as a portable suite.

### What we are *not* doing

- **No IETF / IANA registration.** The spec is open and citable;
  formal standards-body submission is a separate, much later step.
- **No CHANGES vs. RFC 2119 strict-mode declaration.** We use RFC 2119
  conventionally and reference it in the spec README; we don't litigate
  edge cases (SHOULD vs RECOMMENDED).
- **No prose translation of the SDKs.** The spec defines the wire
  contract — what goes on the wire and what verdicts mean. How a given
  language idiomatically constructs and validates that wire is an
  implementation choice, not part of the spec.
- **No deprecation policy yet.** Adding fields is MINOR, removing is
  MAJOR — that's already in `docs/VERSIONING.md`. We add a formal
  deprecation track only when something is first deprecated.

## Consequences

- **+** Third-party implementations have a stable, versioned URL to
  target and cite. "We conform to TrustLayer v0.1" becomes a precise
  claim.
- **+** The wire format is no longer entangled with the SDKs in
  documentation — only in implementation. That distinction is what an
  open standard needs.
- **+** Adding a Go SDK / OTel exporter / any future Slice-4 surface
  is purely a matter of "implement v0.1"; reviewers can ground PRs
  against the spec directly.
- **+** The directory layout maps cleanly onto IETF-style versioning
  if we ever want to publish through a standards body.
- **−** Two artifacts (`spec/v0.1/` and `docs/SCHEMA.md`) means a drift
  risk. We mitigate by treating the spec as authoritative and the dev
  doc as a mirror, and by keeping the dev doc short — anything that
  could drift normatively lives only in the spec.
- **−** A formal spec implies that breaking-change governance will
  eventually need real discussion. That's a feature, not a bug, but
  it does raise the bar for casual schema edits.

## Follow-ups
- Language-agnostic conformance fixture set under `spec/v0.1/fixtures/`
  (`AgentTraceEvent` examples + expected verdicts for given policies).
- HTML rendering of the spec at a stable URL (`/spec/v0.1/` on the
  project's eventual website). Pure publishing concern — the markdown
  source is the artifact.
- A `spec` GitHub label and a "spec-changes" CODEOWNERS rule once the
  project has more than one regular contributor.
