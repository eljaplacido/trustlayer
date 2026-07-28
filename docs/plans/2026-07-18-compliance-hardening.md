# Compliance Hardening And Release Preparation

## Objective

Make the Phase 7 compliance addition fit the existing TrustLayer release
standards and establish a cross-harness agent workflow without introducing a
new orchestration service.

## Scope

- Add `AGENTS.md`, concise project state documents, OpenCode Scout/Plan/Build/
  Review skills, and a canonical verification entry point.
- Package and validate compliance YAML inputs, test the readiness, evidence,
  dashboard-report, and audit generators, and run them in CI.
- Add dashboard tests and remove external system information from committed
  dashboard data.
- Add release-oriented security documentation and CI dependency/secret checks.

## Non-Goals

- Do not change the normative TrustLayer wire protocol.
- Do not assert legal compliance or connect production trace stores.
- Do not publish packages, create a release, or alter production deployment
  credentials.

## Acceptance Criteria

- Compliance system and framework inputs are schema validated.
- Compliance code has automated tests and a CI job.
- Dashboard has coverage for the Compliance pane and contains no external
  project registry data by default.
- A documented local verification gate and GitHub security gate exist.
- Existing Rust, TypeScript, dashboard, Python SDK, Hermes, and MCP checks are
  run when tooling is available; missing toolchains are reported explicitly.
