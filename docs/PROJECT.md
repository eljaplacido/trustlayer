# TrustLayer Project

## Purpose

TrustLayer is a self-hostable governance, policy, observability, and compliance
plane for tool-using AI agents. It provides a versioned event protocol, SDKs,
a Rust guardian sidecar, trace storage, dashboards, Hermes memory tooling, MCP
integration, and machine-readable compliance evidence.

## Architecture

- Rust: `core-rs/` policy evaluator, HTTP sidecar, trace stores, metrics.
- SDKs: Python, TypeScript, and Go implementations of the same wire contract.
- Python services: Hermes under `skills/hermes/`, MCP under `mcp-server/`, and
  compliance tools under `compliance/`.
- Frontend: `dashboard/` React and Vite application.
- Protocol: normative documents and conformance fixtures in `spec/`.

## Critical Constraints

- `spec/` is normative; SDK and core schema changes must remain conformant.
- Instrumentation failures must not take down the host agent.
- Never commit tokens, credentials, private trace data, or third-party system
  registry data to this repository.
- Guardian deployments exposed beyond loopback require authentication and TLS
  termination in the deployment environment.
- Compliance output is evidence support, not legal advice or a certification.

## Core Commands

- Full repository verification: `./scripts/verify.sh`
- Focused compliance checks: `make compliance`
- Run a readiness scan: `python -m compliance.src.readiness_scanner --project-dir .`
- Run the guardian: `cd core-rs && cargo run --release --features server --bin trustlayer-guardian`
- Build dashboard: `cd dashboard && npm run build`

## Developer entry points

- Integrate with an existing stack: [`docs/INTEGRATING.md`](./INTEGRATING.md)
- Root walkthrough: [`README.md`](../README.md)
- Agent/contributor contract: [`AGENTS.md`](../AGENTS.md)
- OpenCode skills: `.opencode/skills/{scout,plan,build,review,compliance}/`

## Release Gate

Run `./scripts/verify.sh`, inspect `docs/RELEASE.md`, and ensure CI is green
before tagging or publishing. Run affected end-to-end checks when changing API,
storage, policy, dashboard, MCP, or compliance integration behavior.
