# Current State

## Current Milestone

Phase 7: EU AI Act Compliance Framework — hardening complete; remaining work is
live evidence linking and release publication.

## In Progress

- [ ] Connect evidence linker to a live authenticated trace store.
- [ ] Final green CI on the published branch and human release review.

## Done Recently

- [x] Nested Article 50 scanner alignment (ADR-016).
- [x] Go SDK `DISCLOSURE_SHOWN` / `CONTENT_MARKED` parity + round-trip tests.
- [x] Compliance lint/typecheck in `scripts/verify.sh`; CI compliance job.
- [x] Repository agent contract (`AGENTS.md`) and Scout/Plan/Build/Review/
      Compliance OpenCode skills.
- [x] Local `./scripts/verify.sh test` green (2026-07-28).

## Blockers

- Compliance evidence linking must be validated against a live authenticated
  trace store before it can be presented as runtime evidence.
- GitHub publication requires a final green CI run and human review of release
  credentials, repository visibility, and release notes.

## Next Recommended Action

Connect the evidence linker to a local guardian/trace store with auth enabled
and record a dogfood report; then open the release PR.

## Last Verified State

- Local gate: `./scripts/verify.sh test` exit 0 on 2026-07-28.
- Phase 7 compliance tooling is still largely uncommitted relative to
  `origin/main` and must be reviewed as a cohesive change set before release.
