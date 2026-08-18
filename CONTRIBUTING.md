# Contributing to TrustLayer

TrustLayer is an open architectural standard and protocol for transparent,
reliable, and traceable agentic AI governance. We welcome contributions
that advance the protocol specification, reference implementations, SDKs,
and tooling.

Participation is governed by the [Code of Conduct](./CODE_OF_CONDUCT.md).
Suspected vulnerabilities go through the private route in
[`docs/SECURITY.md`](./docs/SECURITY.md), never a public issue.

**Not sure where to start?** A new SDK in an uncovered language is the most
self-contained contribution here: `spec/v0.1/` specifies the wire format
precisely enough to implement against, and `spec/v0.1/fixtures/` is a
ready-made conformance suite — every event type has a fixture, and passing all
of them is most of what conformance means.

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
├── AGENTS.md             Agent/contributor operating contract
├── core-rs/              Rust core + trustlayer-guardian sidecar
├── sdks/python/          Python SDK (trustlayer-sdk)
├── sdks/typescript/      TypeScript SDK (@trustlayer/sdk)
├── sdks/go/              Go SDK
├── skills/hermes/        Hermes memory + compliance graph subagent
├── compliance/           EU AI Act readiness, evidence, audit packages
├── mcp-server/           MCP bridge (FastMCP stdio + SSE)
├── dashboard/            React + Vite observability UI
├── scripts/verify.sh     Canonical local release gate
├── spec/                 Versioned, normative protocol specification
├── obsidian_vault/       ADRs, memory traces, reflections, compliance notes
├── .opencode/skills/     Scout / Plan / Build / Review / Compliance skills
└── docs/                 SCHEMA, ARCHITECTURE, INTEGRATING, STATUS
```

## Development setup

### Prerequisites
- Python 3.11+
- Node.js 20+
- Rust 1.75+
- Go 1.22+
- For `./scripts/verify.sh security` only — neither ships with a language
  toolchain, so a fresh clone does not have them:
  ```bash
  cargo install cargo-audit
  python3 -m pip install pip-audit
  ```
- (Optional) GitNexus for code-graph generation

### Quickstart
```bash
# Clone and install all layers
git clone https://github.com/eljaplacido/trustlayer.git
cd trustlayer

# Python SDK + Hermes
cd sdks/python && pip install -e .[dev] && cd ../..
# types-PyYAML is what Hermes' `mypy --strict` gate needs; CI installs it
# explicitly, so without it here `verify.sh test` fails on a fresh clone.
cd skills/hermes && pip install -e ../../sdks/python types-PyYAML

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

Preferred (full monorepo gate):

```bash
./scripts/verify.sh test          # unit/lint across all layers
./scripts/verify.sh security      # secret grep + dependency audits
./scripts/verify.sh compliance    # compliance pytest only
make verify                       # same as ./scripts/verify.sh
```

Per-layer (when iterating):

```bash
cd sdks/python && pytest
cd skills/hermes && pytest
cd compliance && python -m pytest
cd sdks/typescript && npm test
cd core-rs && cargo test --features server
cd mcp-server && PYTHONPATH=src:../sdks/python/src:../skills python -m pytest
cd dashboard && npm test
cd sdks/go && go vet ./... && go test ./... -race
```

Agentic contributors: read [`AGENTS.md`](./AGENTS.md) and use the
Scout → Plan → Build → Review skills under `.opencode/skills/`.

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

- [ ] `./scripts/verify.sh test` is green (or report exact failures)
- [ ] New behavior has test coverage
- [ ] Schema changes are mirrored across Python, TypeScript, Go, and Rust
- [ ] Architectural changes have an ADR + `docs/DECISIONS.md` index row
- [ ] `docs/CURRENT_STATUS.md` / `docs/CURRENT_STATE.md` updated when milestones move
- [ ] No secrets, private traces, or third-party system registries committed
- [ ] Signed-off commits (`git commit -s`) preferred

## License

By contributing, you agree that your contributions will be licensed
under the Apache License 2.0.
