---
date: 2026-05-13
phase: 4
status: complete
tags: [development, milestone, rust, guardian, policy]
links:
  - "[[../01_Architecture/ADR-004-Cynepic-Guardian-Policy-Engine]]"
  - "[[../02_Agent_Skills/Guardian_Manifest]]"
  - "[[../../docs/CURRENT_STATUS]]"
---

# Phase 4 — cynepic-guardian Shipped

## What landed
- **Rust core (`core-rs/`)** went from stub to a real library:
  - `schema.rs` mirrors `docs/SCHEMA.md` via serde, with
    `deny_unknown_fields` on the envelope. Cross-language test verifies
    Pydantic-emitted JSON parses cleanly.
  - `policy.rs` parses a JSON CSL document into `Policy` /
    `PolicyRule` / `MatchSpec`.
  - `guardian.rs` walks rules in declaration order, returns the first
    match, defaults to `PASS` (or `ESCALATE` for CHAOTIC events).
  - `error.rs` provides `Error` / `Result` via `thiserror`.
- **HTTP sidecar (`trustlayer-guardian` binary)** built on Axum 0.7 +
  Tokio. `POST /v1/check`, `GET /healthz`, graceful shutdown on
  Ctrl-C. Configurable via `TRUSTLAYER_POLICY` and `TRUSTLAYER_BIND`.
- **Python SDK** gained `GuardianClient` + `Verdict`. Fail-open by
  default; `fail_open=False` for regulated workloads.
- **19 Rust tests** pass (15 unit + 4 cross-language).
- **8 new Python tests** cover request shape, fail-open / fail-closed
  paths, unexpected verdict values, 5xx handling, and the context
  manager.
- **End-to-end smoke**: live server, four scenarios
  (external_llm → FAIL, complex_human_callout → ESCALATE,
  calculator → PASS, novel CHAOTIC tool → ESCALATE). All matched
  expected behaviour.

## Why these choices
See [[../01_Architecture/ADR-004-Cynepic-Guardian-Policy-Engine]] for
the rationale. Highlights: JSON CSL for trivial tooling, ordered
rule evaluation as the audit trail, Cynefin-aware default escalation,
HTTP transport for language-agnostic integration, fail-open SDK so
instrumentation never breaks the host agent.

## Known gaps
- `MatchSpec` can't express predicates on payload fields beyond
  `tool_name`. PII-pattern blocking is a follow-up.
- No TS SDK guardian client yet (parity comes in Phase 4.5).
- `cargo clippy` and `cargo fmt` were not installed in this session
  (minimal rustup profile). `rustup component add clippy rustfmt` is
  a one-liner when you want to enforce them in CI.
- The HTTP transport adds ~100µs per check. Acceptable for now; an
  in-process embedding via `pyo3` is the long-term answer when
  performance demands it.

## Next up (Phase 4.5 / Phase 5)
- **4.5** — TypeScript SDK guardian client (mirrors `GuardianClient`).
- **4.5** — `Tracer.check()` helper that wraps a tool call in a guardian
  call plus the resulting `POLICY_CHECK` event.
- **5**   — TrustLayer dashboard (Vite + React over the Obsidian vault).
- **5**   — MCP server exposing Hermes ingest and the guardian as MCP
  tools so other agents can use TrustLayer through the standard
  protocol.
