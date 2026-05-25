# TrustLayer Protocol Specifications

This directory is the **citable source of truth** for the TrustLayer
wire protocol. Documents here are normative; the SDKs and the Rust core
implement what these documents require.

| Version | Status | Directory |
|---|---|---|
| **v0.1** | Active | [`v0.1/`](./v0.1/) |

## Versioning

The directory name pins the wire-format version. A `MINOR` bump opens a
new directory next to this one; a frozen directory is not edited
afterward except for editorial fixes (typos, broken links). See
[`docs/VERSIONING.md`](../docs/VERSIONING.md) and
[ADR-010](../obsidian_vault/01_Architecture/ADR-010-Formal-Spec-Layout.md)
for the policy.

## Relationship to other docs

- [`docs/SCHEMA.md`](../docs/SCHEMA.md) is the **implementation mirror**:
  developer-friendly, evolves with the SDK code. It cites the
  current spec version; the spec does not cite it.
- ADRs (`obsidian_vault/01_Architecture/ADR-*.md`) are **decision
  records**: why a choice was made. The spec is the **requirements
  record**: what implementations must do.

## Conformance

See [`v0.1/06-conformance.md`](./v0.1/06-conformance.md) for what an
implementation must support to claim "TrustLayer v0.1 compliant."
