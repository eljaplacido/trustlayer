# Release Process

This document describes how to tag and publish TrustLayer releases.

## Pre-release checklist (all releases)

- [ ] All CI jobs green across the matrix (Rust, Python SDK, Hermes,
  MCP server, TypeScript SDK, Go SDK, Dashboard)
- [ ] `cargo fmt --check` clean
- [ ] `cargo clippy --features server --all-targets -- -D warnings` clean
- [ ] `mypy` + `ruff` clean on all Python packages
- [ ] `tsc --noEmit` clean on TypeScript packages
- [ ] `go vet ./...` clean on Go SDK
- [ ] Compliance tooling tests and schema validation clean
- [ ] Dependency and secret-hygiene CI job green
- [ ] No generated compliance report, audit package, trace, or system registry
  from a third-party environment is committed without an explicit data review
- [ ] Any schema changes are mirrored across Python / TypeScript / Rust
  / Go and have a cross-language round-trip test
- [ ] `docs/SCHEMA.md` matches the current wire-format version
- [ ] `CHANGELOG.md` has the release date and version section
- [ ] New architectural decisions have ADRs in
  `obsidian_vault/01_Architecture/`
- [ ] `docs/CURRENT_STATUS.md` reflects the latest phase/slice status
- [ ] `docs/SECURITY.md` deployment baseline has been reviewed for the target
  environment

## Wire-format versioning

The wire format is versioned by directory in `spec/`:

| Change | Action |
|---|---|
| Breaking (MAJOR) | New directory: `spec/v<N+1>.0/` |
| Additive (MINOR) | New directory: `spec/v<N>.<M+1>/` |
| Editorial (PATCH) | Edit existing spec files directly |

The `spec/v0.1/` directory is frozen. Do not edit it except for typos.

## Tag format

Each component is tagged independently:

```
<component>-v<MAJOR>.<MINOR>.<PATCH>
```

Examples:
- `python-sdk-v0.1.0`
- `rust-core-v0.1.0`
- `typescript-sdk-v0.1.0`
- `go-sdk-v0.1.0`
- `mcp-server-v0.1.0`
- `wire-format-v0.1`   (wire format tags omit PATCH)
- `dashboard-v0.1.0`

## Step-by-step

### 1. Bump versions

Edit the `version` field in each component's manifest:
- `sdks/python/pyproject.toml`
- `sdks/typescript/package.json`
- `core-rs/Cargo.toml`
- `mcp-server/pyproject.toml`
- `dashboard/package.json`
- `sdks/go/go.mod` (no version field; use git tags for pkg.go.dev)

### 2. Update CHANGELOG.md

Move items from `## [Unreleased]` to a dated version section:
```markdown
## [0.1.0] — YYYY-MM-DD
```

### 3. Commit and tag

```bash
git add -A
git commit -m "release: tag v0.1.0"
git tag python-sdk-v0.1.0
git tag rust-core-v0.1.0
git tag typescript-sdk-v0.1.0
git tag go-sdk-v0.1.0
git tag mcp-server-v0.1.0
git tag dashboard-v0.1.0
git push origin main --tags
```

### 4. Publish packages

```bash
# Python SDK
cd sdks/python && hatch build && hatch publish

# MCP server
cd mcp-server && hatch build && hatch publish

# Rust crate
cd core-rs && cargo publish

# TypeScript SDK
cd sdks/typescript && npm publish

# Go SDK — tagged version is automatically available at pkg.go.dev
# github.com/eljaplacido/trustlayer/sdks/go

# Dashboard — static build, deploy to your host
cd dashboard && npm run build
```

### 5. Publish spec

Copy or symlink the spec to a stable URL. The canonical location:
```
https://github.com/eljaplacido/trustlayer/blob/main/spec/v0.1/README.md
```

### 6. Create GitHub Release

Create a release from the tag with:
- A summary of changes from `CHANGELOG.md`
- Links to the spec for this version
- Docker image references if publishing to a registry

## Post-release

- Bump the version in each manifest to the next development version
  (e.g. `0.1.0` → `0.2.0-dev` or `0.1.1`)
- Re-add `## [Unreleased]` to the top of `CHANGELOG.md`
- Announce on relevant channels
