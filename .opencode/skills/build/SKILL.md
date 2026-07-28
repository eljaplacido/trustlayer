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
