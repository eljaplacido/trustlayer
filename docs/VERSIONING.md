# Versioning

TrustLayer is a protocol with several reference implementations. We
version each layer independently with [Semantic Versioning
2.0.0](https://semver.org/) — and we apply SemVer to the **wire format**
the same way we apply it to APIs.

The wire format is the contract. The SDKs, the guardian, the trace
store, and the MCP server all derive their compatibility guarantees
from how they evolve `docs/SCHEMA.md`.

---

## What versions things have

| Component | Versioned in | Cadence |
|---|---|---|
| `trustlayer-sdk` (Python) | `sdks/python/pyproject.toml` | Per SDK release |
| `@trustlayer/sdk` (TypeScript) | `sdks/typescript/package.json` | Per SDK release |
| `trustlayer-core` (Rust crate) | `core-rs/Cargo.toml` | Per Rust release |
| `trustlayer-mcp` (Python) | `mcp-server/pyproject.toml` | Per MCP-server release |
| `@trustlayer/dashboard` | `dashboard/package.json` | Per dashboard release |
| Wire format | `docs/SCHEMA.md` (see *Wire-format version* below) | Independent |

All components are currently **0.x**. Pre-`1.0`, minor versions may
contain breaking changes; we still tag them clearly in `CHANGELOG.md`
and document the migration. From `1.0` onwards we follow strict SemVer.

---

## Wire-format version

The wire-format version is declared **normatively** by the
[`spec/v0.1/`](../spec/v0.1/README.md) directory name and the
`schema_version` field in its frontmatter. [`docs/SCHEMA.md`](./SCHEMA.md)
mirrors that constant (currently `0.2`) for developer convenience.

The version follows the protocol rules below, **not** the version of any
particular SDK. Two implementations are compatible if and only if they
share the same major wire-format version. The directory `spec/v0.1/`
is frozen — wire-format MINOR bumps open a new
directory (`spec/v0.2/`, etc.); old directories are not edited beyond
editorial fixes.

### MAJOR — breaking changes
- Removing or renaming a field on `AgentTraceEvent` or any payload type.
- Changing the type of an existing field (e.g. `string` → `int`).
- Removing or renaming an enum value of `event_type` or `cynefin_domain`.
- Tightening validation in a way that rejects payloads previously
  considered valid.
- Changing the trace-store HTTP routes' paths or response shapes in a
  non-additive way (e.g. removing `event_count` from `/v1/sessions`).

### MINOR — backwards-compatible additions
- Adding a new optional field to `AgentTraceEvent` or a payload.
- Adding a new `event_type` enum value. Old SDKs must treat unknown
  event types as opaque pass-through; this is enforced by tests.
- Adding a new HTTP route to the trace store / guardian.
- Adding a new optional query parameter to an existing route.
- Adding a new MCP tool.

### PATCH — no observable contract change
- Editorial fixes in `docs/SCHEMA.md` that do not change behaviour.
- Bug fixes that align an implementation with the spec.
- Documentation, comments, examples.

---

## Component-version rules (per-package)

Each component follows SemVer against its **public API**, which is
the surface external code depends on:

- **Python SDK** — anything importable from `trustlayer.*` that isn't
  prefixed with `_`. Breaking change → MAJOR. New helper, new optional
  parameter → MINOR. Internal refactor with identical behaviour →
  PATCH.
- **TypeScript SDK** — anything exported from `@trustlayer/sdk`.
- **Rust core** — anything `pub` in `trustlayer_core`. The
  `trustlayer-guardian` binary's HTTP surface is governed by the
  wire-format version, not by the crate version.
- **MCP server** — the set of tool names + their input schemas. Adding
  a tool is MINOR; renaming one is MAJOR.
- **Dashboard** — internal product; bumps follow whatever consumer
  changes the user can see. Most are PATCH.

An SDK release that simply adopts a newer wire-format MINOR is itself a
MINOR release. An SDK release that drops support for an older
wire-format MAJOR is a MAJOR release.

---

## Compatibility matrix

We commit to interoperability across the **current major** of the wire
format. Within `wire-format 0.x`, all reference implementations on the
same `0.x` line speak to each other. We will publish a compatibility
matrix in this document at the first non-zero major bump.

---

## Release process

1. Land all changes for the release on `main`.
2. Update `CHANGELOG.md`: move items from `## [Unreleased]` into a new
   versioned section with today's date.
3. Bump the affected component's `version` field.
4. If the wire format changed, bump `SCHEMA_VERSION` in
   `docs/SCHEMA.md` and add a `### Wire format` row to the changelog
   entry.
5. Tag the release. Tag format: `<component>-v<MAJOR>.<MINOR>.<PATCH>`,
   e.g. `python-sdk-v0.2.0`, `rust-core-v0.3.0`, `wire-format-v0.2`.
6. CI builds and (eventually) publishes — publishing is gated on a
   maintainer for now.

---

## Yanking

If a release ships a broken artifact (wrong dependency, bad schema
migration), we yank it on the package registry and document the
incident in `CHANGELOG.md` under the affected version with a `YANKED`
marker. We do not rewrite history.
