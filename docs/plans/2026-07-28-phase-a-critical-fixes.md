# Phase A Critical Fixes — Complete

## Objective

Close release blockers for Phase 7 compliance: Go event parity, nested
Article 50 scanner alignment, and compliance coverage in the local verify gate.

## Acceptance (met)

- [x] Go SDK accepts and round-trips `DISCLOSURE_SHOWN` / `CONTENT_MARKED`.
- [x] Readiness scanner reads nested `disclosure_config` / `marking_config`.
- [x] Compliance fixtures use the nested example shape.
- [x] `scripts/verify.sh test` includes compliance ruff/mypy/pytest.
- [x] ADR-016 recorded; state docs updated.
- [x] OpenCode compliance skill added.
- [x] Local `./scripts/verify.sh test` exit 0 (2026-07-28).

## Out of scope (follow-up)

- Live authenticated evidence-linker dogfood against a running guardian.
- Commit/push/release publication (human-gated).
