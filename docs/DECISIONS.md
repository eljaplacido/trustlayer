# Decision Index

The authoritative architecture records are append-only ADRs in
`obsidian_vault/01_Architecture/`.

| ID | Decision | Status | Date | Rationale |
|---|---|---|---|---|
| ADR-015 | Pluggable trace stores with Postgres option | Accepted | 2026-06-22 | Scale the guardian without changing the wire/API contract. |
| GOV-001 | Repository agent operating contract in `AGENTS.md` | Accepted | 2026-07-18 | Keep OpenCode, Claude Code, and Cursor workflows aligned around one auditable contract. |
| GOV-002 | `scripts/verify.sh` is the local release gate | Accepted | 2026-07-18 | A dependency-free, cross-platform entry point fits the polyglot monorepo better than a new task-runner dependency. |
| ADR-016 | Nested Article 50 config + cross-SDK event parity | Accepted | 2026-07-28 | Align readiness scanner with `system.schema.json`; keep Go/Python/TS/Rust event types in lockstep for W4. |

Material architectural decisions must also receive a dated ADR before merge.
