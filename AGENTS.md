# Project Agent Operating Contract

## Mission

Work toward the outcomes and constraints in `docs/PROJECT.md`. Treat the
repository, normative specification, tests, and documented decisions as the
source of truth.

## Required Workflow

For every non-trivial task:

1. Read this file, `docs/PROJECT.md`, `docs/CURRENT_STATE.md`, and relevant
   decisions in `docs/DECISIONS.md` and `obsidian_vault/01_Architecture/`.
2. Scout before editing: inspect relevant code, tests, interfaces,
   dependencies, and recent Git changes.
3. Produce a concise plan before editing.
4. Obtain explicit approval before changes to architecture, public APIs,
   schemas, infrastructure, security, or data handling.
5. Implement only the approved scope, with tests and documentation.
6. Run `./scripts/verify.sh` and the affected end-to-end checks.
7. Do not claim completion when a required check fails. Report the exact
   command, failure, risk, and follow-up instead.

## Change Classification

- **Trivial:** isolated typo, formatting, or explicitly specified one-file
  change. Implement directly and run applicable checks.
- **Standard:** behavior within the existing architecture. Scout, plan,
  build, verify, and review.
- **High-risk:** architecture, auth/security, schemas/migrations, data access,
  public APIs, production configuration, or destructive actions. Require a
  design proposal and human approval before implementation.

## Engineering Constraints

- Prefer the smallest correct change and existing patterns.
- Do not modify unrelated files or expose secrets, credentials, personal data,
  or restricted data.
- Preserve backwards compatibility unless an approved plan says otherwise.
- The normative wire contract is `spec/`; update its implementation mirrors
  and cross-language tests together when it changes.
- Use an isolated worktree for parallel or non-trivial implementation work.

## Evidence And State

- Store accepted plans in `docs/plans/`.
- Record material decisions in `docs/DECISIONS.md` and a dated ADR when the
  architecture changes.
- Update `docs/CURRENT_STATE.md` and `docs/CURRENT_STATUS.md` when milestones,
  blockers, or next steps change.
- Task summaries must name changed files, decisions, exact verification
  commands and outcomes, residual risks, and state updates.
