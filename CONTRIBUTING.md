# Contributing to TrustLayer

Thanks for your interest. TrustLayer is the open governance,
observability, and trust layer for multi-agent AI systems — a protocol
first, a codebase second. Contributions that strengthen the protocol
itself (the wire format, the policy language, the guardian behaviour)
are especially welcome.

This guide is the operational counterpart to `CLAUDE.md`. `CLAUDE.md`
tells coding agents *how* to work inside the repo; this document tells
humans *what* changes are accepted and how to propose them.

---

## The wire format is the contract

`docs/SCHEMA.md` is the canonical wire format. **Every SDK mirrors it
byte-for-byte.** The Python (`pydantic`), TypeScript (`zod`), and Rust
(`serde`) representations are kept in lock-step on purpose — a trace
event written by any SDK must round-trip through any other.

When you change the schema:

1. Update `docs/SCHEMA.md` first. The change is not real until it lives
   in the spec.
2. Update the three SDK mirrors in the same PR:
   - `sdks/python/src/trustlayer/schema.py`
   - `sdks/typescript/src/schema.ts`
   - `core-rs/src/schema.rs`
3. Add a cross-language test in `core-rs/tests/cross_language.rs` that
   parses a fixture produced by the Python (or TS) SDK.
4. Bump versions per `docs/VERSIONING.md`.

A PR that touches one mirror but not the others will be sent back.

---

## Architectural decisions

Non-trivial changes — new event types, new layers, new transports, new
storage backends, license-sensitive dependencies — require an ADR.

- ADRs live in `obsidian_vault/01_Architecture/`.
- They are append-only. Once accepted, you don't edit; you supersede
  with a new ADR.
- File name format: `ADR-NNN-<kebab-case-title>.md`. The next number is
  whatever follows the latest ADR currently on `main`.
- Required sections: **Context**, **Decision**, **Consequences**, and
  (where it matters) **Alternatives considered**.

Write the ADR *before* the code, not after. PRs that introduce
architectural change without an ADR will block on a request for one.

---

## Adding a new SDK

The wire format is intentionally minimal so new SDKs are tractable. To
contribute one:

1. Open an ADR proposing the language and the dependency set.
2. Implement the schema as **strict** types (Pydantic v2, Zod, serde
   with `deny_unknown_fields`, Go struct tags + `DisallowUnknownFields`,
   etc.). Unknown fields must fail loudly during development; we'll
   relax that with a versioning story later.
3. Implement at least: `Tracer` (context-managed `tool_call` /
   `instrument_tool`-equivalent), `GuardianClient` (HTTP, fail-open,
   strict verdict validation), and a `Tracer.check()` helper that emits
   a `TOOL_CALL` + the guardian's `POLICY_CHECK` under one `trace_id`.
4. Mirror the Python SDK's test layout: schema tests, transport tests
   (with a fake HTTP client), tracer integration tests, guardian client
   tests (including the fail-open path).
5. Add a runnable example that mirrors
   `sdks/python/examples/end_to_end_demo.py`.

The Python and TypeScript SDKs are the reference implementations. When
in doubt, match their behaviour.

---

## Per-layer commands

You should be able to run every test suite locally before pushing. CI
runs the same commands.

### Rust core (`core-rs/`)
```bash
cd core-rs
cargo fmt -- --check
cargo clippy --features server -- -D warnings
cargo test --features server
```

The `--features server` flag is required — the HTTP sidecar and the
trace-store integration tests live behind it.

### Python SDK (`sdks/python/`)
```bash
cd sdks/python
pip install -e .[dev]
pytest
```

### Hermes (`skills/hermes/`)
```bash
cd skills/hermes
pip install -e ../../sdks/python   # Hermes depends on trustlayer-sdk
pytest
```

### MCP server (`mcp-server/`)
```bash
cd mcp-server
python -m venv .venv
.venv/bin/pip install -e ../sdks/python -e .[dev]
PYTHONPATH=src:../sdks/python/src:../skills .venv/bin/python -m pytest
```

### TypeScript SDK (`sdks/typescript/`)
```bash
cd sdks/typescript
npm install
npm run typecheck
npm test
```

### Dashboard (`dashboard/`)
```bash
cd dashboard
npm install
npm run typecheck
npm test
npm run build
```

---

## Style

- **Rust** — `cargo fmt` + `cargo clippy -- -D warnings`. No `unwrap()`
  on production paths; reserve it for tests and `static` initialisers
  whose values cannot fail.
- **Python** — 3.11+, Pydantic v2, type hints everywhere,
  `from __future__ import annotations` at the top of every module.
  `ruff` for lint where configured.
- **TypeScript** — strict mode, `noUncheckedIndexedAccess`, exported
  interfaces clearly named. No `any` without a comment explaining why.

---

## Tests are the contract for shipped behaviour

- New behaviour ships with at least one new test.
- Refactors keep the existing tests green; they don't rewrite them to
  match the new code.
- Instrumentation must never take down the host agent. Transport errors
  in the SDKs are logged and swallowed; if you add a new emit path, it
  must follow the same rule and you must add a test that proves it.

---

## Pull-request workflow

1. Open an issue or a draft PR with the proposed change.
2. If the change touches the schema or the architecture, link the ADR.
3. Run the full local matrix (see "Per-layer commands"). CI runs the
   same matrix; failing CI is not a path to merge.
4. PR descriptions should include: what shipped, the test counts that
   changed, and (if relevant) the curl smoke / browser smoke you used
   to verify behaviour the tests can't see.
5. Squash-merge by default. The first line of the squash message
   should match the commit-message style already in the history
   (terse imperative, optional body explaining "why").

---

## Reporting issues

- Bugs in the wire format, the policy engine, or the trace-store API
  should include a minimal reproduction and the relevant
  `AgentTraceEvent` JSON.
- Bugs in the SDKs should include the language, version, and the
  smallest possible repro script.
- Security-sensitive issues — please do not open a public issue; reach
  out via the contact listed on the project's GitHub profile.

---

## License

By contributing, you agree that your contributions will be licensed
under the [Apache License, Version 2.0](./LICENSE). No CLA is required.
