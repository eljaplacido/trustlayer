---
name: review
description: Use when a TrustLayer patch requires an independent, read-only review against its plan, tests, security constraints, and release gate.
---

# Review Workflow

Do not edit files. Review scope compliance, correctness, edge cases, security,
privacy, protocol compatibility, tests, validation evidence, and migration or
rollback safety. Report findings as blocker, major, minor, or follow-up, each
with a file path, rationale, and concrete remedy.

## Refusal conditions

Refuse, and say why, when asked to:

- edit files, including to fix something the review found. Repairing a defect
  means reviewing your own work on the next pass; hand the finding back;
- clear a change whose verification evidence is absent, stale, or was produced
  against a different tree than the one under review;
- raise a finding without a file path and a concrete remedy. "This feels
  fragile" is not reviewable, and it costs the author more to interpret than
  to fix;
- pass a change that adds a documented claim no test enforces, or that widens
  a public surface — an event type, an HTTP route, an env var, an exported
  symbol — without the matching documentation;
- soften a blocker to unblock a merge. Re-grade it only if the *evidence*
  changed. Schedule pressure is not evidence;
- treat a green gate as a review. The gate proves the tests that exist pass;
  it says nothing about the ones nobody wrote.
