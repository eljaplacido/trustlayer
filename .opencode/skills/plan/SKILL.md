---
name: plan
description: Use when Scout evidence must be converted into an approved, bounded TrustLayer implementation plan.
---

# Planning Workflow

Create a plan with objective, non-goals, dependencies, files to change,
ordered implementation steps, compatibility and migration effects, tests,
verification commands, rollback notes, and approvals needed. Save approved
plans in `docs/plans/`. Do not implement without explicit approval for
high-risk changes.

## Refusal conditions

Refuse, and say why, when asked to:

- implement. Planning and building are separate steps because the approval
  sits between them;
- plan past the evidence. Where Scout found nothing, the plan says "unknown"
  and adds a step to find out — it does not fill the space with an assumption
  that will read as a finding by the time anyone builds from it;
- produce a plan with no tests or no verification commands. A step nobody can
  check is a step nobody can finish;
- treat a wire-format or event-type change as local. It lands in `core-rs`,
  all four SDKs, the spec, a fixture, and the cross-language tests, in one
  commit, plus an ADR. A plan that touches one of those and not the rest is
  the shape gap G0 had;
- record an approval that was not given, or mark a high-risk change approved
  because it is small. Size is not the risk axis.
