# Cross-Project Observability Dogfood

## Objective

Exercise TrustLayer's full local observability path with real activity from
`agentcenter` and RCCAEF, without replacing either project's existing telemetry
or enforcing new policy decisions during the initial observation period.

## Approved Scope

- Run Guardian, trace storage, dashboard, Hermes, metrics, policy evaluation,
  and the existing compliance report locally with bearer authentication.
- Add opt-in, fail-safe TrustLayer instrumentation at central execution
  boundaries in both projects.
- Record lifecycle, LLM, tool/workflow, policy, escalation, latency, token, and
  error metadata. Do not capture prompt or completion content by default.
- Evaluate TrustLayer policy in shadow mode: record verdicts but do not block
  either project's operations.
- Install the local pre-release Python SDK into each project's existing virtual
  environment for dogfooding.

## Non-Goals

- Do not replace agentcenter DuckDB telemetry, RCCAEF OpenTelemetry, or RCCAEF's
  internal Guardian.
- Do not publish packages, expose services beyond the local machine, or commit
  credentials and generated project reports.
- Do not modify RCCAEF's unrelated in-progress Chuncho work.

## Acceptance Criteria

- Real events from both project agent IDs appear in TrustLayer traces and
  sessions.
- Policy checks, latency/token metadata, and errors are visible where produced.
- Hermes creates session notes and a reflection from the shared trace log.
- `/metrics` reports requests, checks, and ingested events.
- Existing project tests and TrustLayer's verification gate are run and exact
  failures, if any, are reported.

## Approval

Approved by the project owner on 2026-07-19 for shadow-policy deployment.
