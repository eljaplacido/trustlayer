# Contributing to TrustLayer

TrustLayer is an open architectural standard and protocol for transparent,
reliable, and traceable agentic AI governance. We welcome contributions
that advance the protocol specification, reference implementations, SDKs,
and tooling.

## Project principles

1. **The wire format is the contract.** `spec/v0.1/` is the
   normative protocol definition; `docs/SCHEMA.md` is the implementation
   mirror. Every schema change must be mirrored in Python (Pydantic),
   TypeScript (Zod), Go, and Rust in the same commit.

2. **Tests are the contract for shipped behavior.** New behavior gets a
   new test. Refactors keep existing tests green.

3. **Instrumentation must never take down the host agent.** Emit
   failures are logged and swallowed everywhere. The guardian is
   fail-open by default.

4. **ADRs are append-only.** When introducing a new architectural
   decision, write an ADR in `obsidian_vault/01_Architecture/` before
   merging the code.

## Repository layout

```
trustlayer/
├── core-rs/              Rust core + trace-store sidecar
├── sdks/python/          Python SDK (trustlayer-sdk)
├── sdks/typescript/      TypeScript SDK (@trustlayer/sdk)
├── skills/hermes/        Hermes memory subagent
├── mcp-server/           MCP bridge (FastMCP stdio)
├── dashboard/            React + Vite observability UI
├── spec/                 Versioned, normative protocol specification
├── obsidian_vault/       ADRs, memory traces, reflections
└── docs/                 SCHEMA mirror, ARCHITECTURE, VERSIONING, STATUS
```

## Development setup

### Prerequisites
- Python 3.11+
- Node.js 20+
- Rust 1.75+
- Go 1.22+
- (Optional) GitNexus for code-graph generation

### Quickstart
```bash
# Clone and install all layers
git clone https://github.com/trustlayer/trustlayer.git
cd trustlayer

# Python SDK + Hermes
cd sdks/python && pip install -e .[dev] && cd ../..
cd skills/hermes && pip install -e ../../sdks/python

# TypeScript SDK
cd sdks/typescript && npm install && cd ../..

# Go SDK
cd sdks/go && go mod tidy && cd ../..

# Rust core
cd core-rs && cargo build --features server && cd ..

# MCP server
cd mcp-server && python3 -m venv .venv && \
  .venv/bin/pip install -e ../sdks/python -e .[dev] && cd ..

# Dashboard
cd dashboard && npm install && cd ..
```

### Running tests
```bash
# Python SDK
cd sdks/python && pytest

# Hermes
cd skills/hermes && pytest

# TypeScript SDK
cd sdks/typescript && npm test

# Rust core
cd core-rs && cargo test --features server

# MCP server
cd mcp-server && PYTHONPATH=src:../sdks/python/src:../skills .venv/bin/python -m pytest

# Dashboard
cd dashboard && npm test

# Go SDK
cd sdks/go && go vet ./... && go test ./... -race
```

## Making changes

### Schema changes
1. Propose the change in a GitHub issue first.
2. Update `spec/v0.1/` — this is the normative wire-format spec.
3. Update `docs/SCHEMA.md` — this is the implementation mirror.
4. Update `sdks/python/src/trustlayer/schema.py`.
5. Update `sdks/typescript/src/schema.ts`.
6. Update `sdks/go/trustlayer/schema.go`.
7. Update `core-rs/src/schema.rs`.
8. Add/update cross-language round-trip tests and fixtures.

### Adding a new SDK
1. Implement the `AgentTraceEvent` envelope in the target language.
2. Implement `Tracer` + `GuardianClient` with fail-open semantics.
3. Add cross-language tests against the Python SDK's JSON output.
4. Register the SDK in `docs/CURRENT_STATUS.md`.

### Policy contributions
New default policies (`core-rs/policies/`) should:
- Be named descriptively (`financial-services.json`, `healthcare.json`).
- Include comments explaining each rule's rationale.
- Be accompanied by a test in `core-rs/src/policy.rs` or
  `core-rs/src/guardian.rs` that exercises the policy against sample
  events.

## Code style

- **Rust** — `cargo fmt` + `cargo clippy` (no warnings). No `unwrap()`
  on production paths.
- **Python** — `ruff` + `mypy --strict`. Pydantic v2.
  `from __future__ import annotations` in every module.
- **TypeScript** — strict mode, `noUncheckedIndexedAccess`. No `any`
  on public API surfaces.
- **Markdown** — valid YAML frontmatter on all vault notes.

## Pull request checklist

- [ ] Tests pass in all modified layers
- [ ] New behavior has test coverage
- [ ] Schema changes are mirrored across all language implementations
- [ ] Architectural changes have an ADR
- [ ] `docs/CURRENT_STATUS.md` is updated
- [ ] Build succeeds (`cargo build`, `tsc`, etc.)
- [ ] Lint is clean (`cargo clippy`, `ruff`, `tsc --noEmit`)
- [ ] Signed-off commits (`git commit -s`)

## License

By contributing, you agree that your contributions will be licensed
under the Apache License 2.0.
