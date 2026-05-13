---
adr: 004
status: accepted
date: 2026-05-13
tags: [architecture, rust, policy, guardian, csl]
---

# ADR-004 — cynepic-guardian + Constraint Specification Language (CSL)

## Context
Phase 4 of the roadmap is "evaluation": SDKs record events, Hermes
materialises them, and the Rust core decides whether to let an action
proceed. The guardian is the synchronous half of TrustLayer's policy
story — every other layer can pretend it doesn't exist, but if it's
slow or wrong it takes down the whole agent stack.

We need:
- A policy language declarative enough to ship in a JSON file and
  hot-reload at runtime.
- An evaluator deterministic enough for property tests and audit logs.
- A transport that any SDK can call without learning Rust internals.
- A failure model that never makes the host agent unsafe and never
  makes it unavailable (the SDK fail-open default).

## Decision

### 1. CSL is JSON for now
A policy is `{name, rules: [PolicyRule]}`; each rule has `name`,
`match: MatchSpec`, `decision`, and an optional `reason`. The selector
ANDs together up to four predicates: `event_type`, `tool_name`,
`agent_id`, `cynefin_domain`. JSON keeps tooling trivial (any editor,
any diff tool, any CI checker validates it for free) and matches the
wire format the SDKs already speak. A richer DSL (e.g. expression
predicates on payload fields) is a future ADR.

### 2. The evaluator is stateless and ordered
`CynepicGuardian::evaluate(&event) -> Verdict` walks rules in
declaration order and returns the first match. No precedence resolution,
no scoring. This makes the policy file the audit trail: reading the
file top-to-bottom tells you the decision for any event.

### 3. Cynefin-aware default
When no rule matches, the default is `PASS`. **Exception:** events
classified `CHAOTIC` default to `ESCALATE`. The Cynefin framework's
treatment of chaotic events is "act, sense, respond" — escalating to a
human is the safest "act" when the system has no model of the situation.

### 4. HTTP sidecar
The Rust crate ships a binary, `trustlayer-guardian`, that exposes
`POST /v1/check`. Body: `{event, policy_name}`. Response: `Verdict`.
Defaults to `127.0.0.1:8089`. Configurable via `TRUSTLAYER_BIND` and
`TRUSTLAYER_POLICY` environment variables. FFI is a future
optimisation; HTTP keeps language integration trivial.

### 5. Python SDK is fail-open by default
`GuardianClient.check(event)` returns a synthetic
`policy="fallback"` verdict on any transport or schema error. The
default decision is `PASS` (fail-open) — instrumentation cannot make
the host agent unavailable. Opt into `fail_open=False` for regulated
workloads where missing a decision is worse than blocking.

## Consequences

### Positive
- The policy file is the source of truth; reviewing it is reviewing
  the whole governance story.
- Cross-language interop already works: the cross_language.rs
  integration test parses Pydantic-emitted JSON; the live smoke today
  drove four scenarios end-to-end from Python through the Rust server.
- Microsecond-latency evaluation (no allocation in hot path after
  policy load — strings are borrowed from the cached `Policy`).
- The guardian is a single 6 MB statically-linked binary; ship it
  next to any agent process.

### Negative
- The current `MatchSpec` cannot express predicates on payload fields
  beyond `tool_name`. A "block any TOOL_CALL whose payload contains
  PII" rule is out of scope for v1. Follow-up ADR can introduce
  payload-pattern predicates.
- JSON CSL means policy comments must live alongside the file (or as
  `reason` on each rule). YAML support is a future ergonomic
  improvement.
- HTTP, not FFI, costs ~100µs per check. Acceptable for now; an
  in-process embedding via `pyo3` is the long-term answer.

## Operational notes
- Server binary: `target/release/trustlayer-guardian.exe`
- Default policy: `core-rs/policies/default.json`
- Healthcheck: `GET /healthz` returns 200/"ok"
- Run: `cargo run --release --features server --bin trustlayer-guardian`

## Links
- Schema: [[../../docs/SCHEMA.md]]
- Architecture: [[../../docs/ARCHITECTURE.md]]
- ADR-001 — SDK Wedge
- ADR-002 — Hermes Memory Agent
- ADR-003 — Hermes Context / Token / Memory Model
