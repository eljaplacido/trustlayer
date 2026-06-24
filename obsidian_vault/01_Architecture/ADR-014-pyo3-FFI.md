---
adr: 14
title: pyo3 FFI Embedding for the Rust Guardian
date: 2026-05-30
status: accepted
---

# ADR-014 — pyo3 FFI Embedding of the Rust Guardian

## Context

The `cynepic-guardian` ships as an Axum HTTP sidecar (`trustlayer-
guardian`), adding ~100 µs of latency on the hot path (`/v1/check`).
For Python agents running on the same host, this overhead is avoidable
by embedding the Rust evaluator directly in-process.

## Decision

Add an optional `python` feature to `core-rs/Cargo.toml` using
[pyo3](https://pyo3.rs) that exposes `CynepicGuardian` as a native
Python class (`trustlayer_native.TrustLayerGuardian`).

### Design choices

1. **JSON-string API surface** — all inputs and outputs are JSON strings.
   The Python caller does `event.model_dump_json()` → Rust parses with
   `serde_json` → returns verdict as JSON string → Python does
   `json.loads()`. This avoids coupling pyo3 to Pydantic and keeps the
   Rust crate free of Python-specific type mapping.

2. **Same `ArcSwap` hot-reload** — `TrustLayerGuardian.replace_policy()`
   uses the same atomic swap as the HTTP sidecar, so policy hot-reload
   works identically in-process and over the network.

3. **Build with maturin** — the `extension-module` feature of pyo3
   requires a Python-native build tool. `maturin develop` for local dev,
   `maturin build` for wheels.

4. **Independent of the `server` feature** — `python` and `server` are
   orthogonal features. A crate user can enable either, both, or
   neither.

### API

```python
import trustlayer_native

g = trustlayer_native.TrustLayerGuardian(
    '{"name": "default", "rules": [...]}'
)

verdict = g.evaluate(
    '{"trace_id": "...", "agent_id": "a", ...}'
)
# -> '{"decision": "PASS", "rule": null, "reason": null, "policy": "default"}'

g.replace_policy('{"name": "new", "rules": [...]}')  # hot-reload
policy = g.policy()  # returns current policy as JSON
```

### Building

```bash
# Development install
cd core-rs
maturin develop --features python

# Build wheel
maturin build --features python --release
```

### Cargo feature

```toml
[features]
python = ["dep:pyo3"]

[dependencies]
pyo3 = { version = "0.22", optional = true, default-features = false,
         features = ["extension-module", "macros"] }
```

## Consequences

### Positive

- Drops the ~100 µs HTTP overhead for same-host Python agents.
- Same policy engine, same `ArcSwap` semantics, same wire format.
- `python` feature is independent of `server` — no dependency
  entanglement.
- The JSON-string API pattern means zero Python-specific code in
  `core-rs` beyond the thin `ffi.rs` module.

### Negative

- Adds `pyo3` (0.22) as an optional dependency (~20 crates transitive).
- Requires a Python development environment to build with `maturin`.
- Not yet published as a separate Python package (`trustlayer-native`
  doesn't have a `pyproject.toml` for maturin-based builds) — the
  `[package.metadata.maturin]` section is deferred to a follow-up.

## Alternatives considered

1. **Use `cffi` instead of `pyo3`** — rejected. `pyo3` gives us Rust
   traits (`PyClass`, `PyMethods`) that match the codebase's idiomatic
   patterns. `cffi` would require a C ABI wrapper around every function.
2. **In-process HTTP loopback** — rejected. The whole point is to
   eliminate networking overhead.
3. **Make the `python` feature default** — rejected. Most deployments
   use the HTTP sidecar; pyo3 is a niche optimisation for single-host
   Python agents.
