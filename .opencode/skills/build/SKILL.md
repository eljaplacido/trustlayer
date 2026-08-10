---
name: build
description: Use when an approved TrustLayer plan is ready for bounded implementation, documentation, and deterministic verification.
---

# Build Workflow

1. Confirm the worktree, branch, and approved plan.
2. Implement only the approved scope using existing project conventions.
3. Add or update tests and documentation with the implementation.
4. Run `./scripts/verify.sh` and affected end-to-end checks.
5. Report changed files, validation evidence, limitations, and state updates.

## Refusal conditions

Refuse, and say why, when asked to:

- implement outside the approved scope. Adjacent work that looks obviously
  right is still unreviewed work; note it and leave it;
- make a red gate green by weakening it — deleting or skipping a failing test,
  loosening an assertion, relaxing a lint or type setting, or adding an
  `ignore`. Fix the code, or report the failure. This is the single refusal
  most likely to be requested under time pressure, and the one that removes
  the evidence that anything was ever wrong;
- ship behaviour with no test. Working agreement 1: new behaviour gets a new
  test, refactors keep the existing ones green;
- add a claim to the documentation that no test enforces. A documented
  invariant nothing checks is true only until someone edits the file — that is
  how `.claude/skills` came to be ignored by git while the docs described the
  symlinks as canonical;
- report the work done when `./scripts/verify.sh` has not run, did not pass,
  or was not run over the changes as committed. State what failed instead;
- change the wire format in fewer than all five implementations, or without a
  fixture and a spec update in the same commit.
