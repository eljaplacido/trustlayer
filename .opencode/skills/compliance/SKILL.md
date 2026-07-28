---
name: compliance
description: Use when working on TrustLayer EU AI Act / governance compliance tooling, system registries, readiness scans, evidence linking, audit packages, or Article 50 event types.
---

# Compliance Workflow

## Scope

- `compliance/` schemas, controls, scanner, evidence linker, report/audit generators
- Dashboard Compliance pane consumers of readiness JSON
- Cross-SDK event types used as evidence (`DISCLOSURE_SHOWN`, `CONTENT_MARKED`)
- Hermes `07_Compliance/` graph notes when vault integration changes

## Rules

1. Read `docs/PROJECT.md`, `docs/CURRENT_STATE.md`, `compliance/README.md`, and
   ADR-016 before editing.
2. Treat `compliance/schemas/*.schema.json` and `spec/` as normative. Do not
   invent flat `article_50` fields; use nested `disclosure_config` /
   `marking_config` as in `compliance/examples/system.yaml`.
3. Compliance output is evidence support, not legal advice or certification.
4. Never commit third-party system registries, live traces, tokens, or private
   audit packages.
5. Wire-contract event type changes must land together in Python, TypeScript,
   Go, Rust, cross-language tests, and control `evidence_query` definitions.

## Standard Commands

```bash
# Focused compliance tests
./scripts/verify.sh compliance
# or
make compliance

# Full local gate (includes compliance lint + tests)
./scripts/verify.sh test

# Readiness scan against a project that has system.yaml
python -m compliance.src.readiness_scanner --project-dir /path/to/project
```

## Change Checklist

1. Update schema and example YAML together.
2. Update scanner / linker / generators and their tests.
3. If event types change, update all SDKs + `core-rs` + cross-language tests.
4. Run `./scripts/verify.sh compliance` and, for release-path work,
   `./scripts/verify.sh test`.
5. Update `docs/CURRENT_STATE.md` / `docs/CURRENT_STATUS.md` when milestone
   status changes; add an ADR for architecture decisions.
