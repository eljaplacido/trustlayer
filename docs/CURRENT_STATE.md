# Current State

## Current Milestone

Phase 8: Compliance Depth, Agentic Trust, and the Evaluator Layer.

Shipped: event-type lockstep (8.0), Art. 12 evidence integrity (8.1), evidence
query v2 with assurance tiers (8.2), the remediation guidance engine (ADR-024),
and the 8.3 event types plus `parent_trace_id`.

## In Progress

- [ ] ADR-019 remainder: workflow graph metrics, tool privilege lattice,
      untrusted-to-privileged flow detection.
- [ ] ADR-020 `evaluators/`, ADR-021 Annex IV documents, ADR-022 incident
      pipeline, ADR-023 workbench UIX.

## Known deferrals (stated, not discovered)

- **Postgres integrity parity** — the backend answers `501` for the integrity
  routes because it maintains no chain. CI has no database, and untested SQL
  behind an Art. 12 tamper-evidence claim is worse than an honest `501`.
  Deployments needing horizontal scale *and* Art. 12 integrity run JSONL.
- **Streaming evidence evaluation** (ADR-018 §5) — the engine materialises the
  event list. Correct at current volumes, a real limit at scale.
- **`scope` / `window`** in evidence queries are rejected by validation rather
  than silently ignored.
- **`/v1/integrity/verify` attests the chain the running process holds.** It
  does not re-read the store per request, so an edit made behind a live server
  is caught on the next cold read rather than by that server. Deliberate —
  re-reading per request would make an auditor's call a DoS lever against
  ingest. Normative in spec §5.12.3.

## Done Recently

- [x] **Evidence linker validated against a live authenticated trace store**
      (2026-08-09). Ran against a bearer-token guardian holding real emitted
      events: `art-12.1` and `art-14.1` escalated `declared` → `evidenced`
      (`satisfied`, population 6) and integrity resolved `unchained` →
      `verified` across all 35 controls. Assurance correctly stayed at
      `evidenced` rather than `verified` — the third, independent confirmation
      is what `verified` requires, and a chain the same system produced is not
      independent of it.
- [x] Nested Article 50 scanner alignment (ADR-016).
- [x] Go SDK `DISCLOSURE_SHOWN` / `CONTENT_MARKED` parity + round-trip tests.
- [x] Compliance lint/typecheck in `scripts/verify.sh`; CI compliance job.
- [x] Repository agent contract (`AGENTS.md`) and Scout/Plan/Build/Review/
      Compliance OpenCode skills.
- [x] Local `./scripts/verify.sh test` green (2026-08-09).
- [x] Developer docs: root README stack recipes + Art. 50; `docs/INTEGRATING.md`;
      CONTRIBUTING verify gate; skills index.

## Blockers

- GitHub publication requires a final green CI run and human review of release
  credentials, repository visibility, and release notes.
- Nothing is published yet: no git tag, and no artifact on PyPI, npm,
  crates.io, or pkg.go.dev.

## Next Recommended Action

Open the release PR: CI green, then human review of visibility, credentials,
and release notes. Package publication is a separate, deliberate step.

## Last Verified State

Local gate `./scripts/verify.sh test` exit 0 on 2026-08-09 (lint, typecheck and
tests for every language):

| Suite | Passing |
|---|---|
| Rust core (`--features server`) | 207 |
| Compliance (Python) | 222 |
| TypeScript SDK | 61 |
| Dashboard | 46 |
| Python SDK | 60 (+16 OTel, skipped unless the `otel` extra is installed) |
| Hermes | 57 |
| MCP server | 21 |
| Go SDK | green (`go vet` clean, `-race`) |

Dogfooded against a live sidecar on the same date, not only unit-tested:

- Guardian served `PASS` and `FAIL` verdicts from `policies/default.json`;
  bearer auth returned `401` unauthenticated and `200` with the token, and
  `/healthz` stayed open as specified.
- All five Art. 12 evidence gauges appeared in `/metrics` alongside the verdict
  counters, ingest total and latency histogram.
- The hash chain verified clean, then reported `ok: false` with the exact
  `first_bad_seq` after an event was edited on disk and the store re-read.
  A signed Ed25519 checkpoint verified against its published public key.
- The OTel bridge emitted real spans through the OpenTelemetry SDK with
  `trustlayer.*` attributes and latency-derived durations.
- The compliance toolkit ran end to end on TrustLayer itself: readiness scan,
  remediation plan, audit package, and the evidence linker against the live
  authenticated store.
