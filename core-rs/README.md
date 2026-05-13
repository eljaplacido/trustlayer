# trustlayer-core (Rust)

The synchronous half of TrustLayer: schema, CSL policy parser, and the
`cynepic-guardian` evaluator. Ships as both a library
(`trustlayer_core`) and a binary (`trustlayer-guardian`) that exposes
the evaluator over HTTP.

See [ADR-004](../obsidian_vault/01_Architecture/ADR-004-Cynepic-Guardian-Policy-Engine.md)
for the design rationale.

## Build & test

```bash
cargo check --features server
cargo test  --features server          # 15 unit + 4 cross-language
cargo build --release --features server --bin trustlayer-guardian
```

When the `clippy` and `rustfmt` components are installed
(`rustup component add clippy rustfmt`):

```bash
cargo clippy --features server --all-targets -- -D warnings
cargo fmt --check
```

## Run the guardian server

```bash
# defaults: 127.0.0.1:8089, policy from ./policies/default.json
TRUSTLAYER_POLICY=./policies/default.json \
TRUSTLAYER_BIND=127.0.0.1:8089 \
cargo run --release --features server --bin trustlayer-guardian
```

## Wire contract

```text
POST /v1/check
  { "event": <AgentTraceEvent>, "policy_name": "default" }
-> 200 { "decision": "PASS"|"FAIL"|"ESCALATE", "rule": "...", "reason": "...", "policy": "..." }

GET /healthz -> 200 "ok"
```

## Layout

```
core-rs/
├── Cargo.toml
├── policies/
│   └── default.json       Example CSL policy
├── src/
│   ├── lib.rs             Re-exports
│   ├── error.rs           Error / Result
│   ├── schema.rs          AgentTraceEvent mirror
│   ├── policy.rs          Policy / PolicyRule / MatchSpec
│   ├── guardian.rs        CynepicGuardian + Verdict
│   └── bin/
│       └── guardian.rs    Axum HTTP server
└── tests/
    └── cross_language.rs  Parses Pydantic-emitted JSON
```
