# TrustLayer Architecture

TrustLayer is the **open governance, observability, and trust layer for
multi-agent AI systems.** It is built as three loosely-coupled layers
around a single canonical wire format.

## The wire format is the contract

Every component speaks `AgentTraceEvent` (see
[`SCHEMA.md`](./SCHEMA.md)). The Python (`trustlayer-sdk`) and TypeScript
(`@trustlayer/sdk`) clients ship Pydantic and Zod definitions that mirror
the schema byte-for-byte; round-tripping the same JSON between them is a
test (see `sdks/*/tests/`). The Rust core (Phase 4) and Hermes (Phase 3)
both consume the same envelope without re-deriving types.

## The three layers

```
                                   AgentTraceEvent
                                   ────────────────
                                          │
   ┌──────────────────────────────────────┼──────────────────────────────────┐
   │                                      │                                  │
   ▼                                      ▼                                  ▼

╔═══════════════════════╗   ╔═══════════════════════╗   ╔═══════════════════════╗
║  1. INSTRUMENT        ║   ║  2. EVALUATE          ║   ║  3. REFLECT           ║
║  (Phase 2, shipped)   ║   ║  (Phase 4, shipped)   ║   ║  (Phase 3, shipped)   ║
║                       ║   ║                       ║   ║                       ║
║  sdks/python/         ║   ║  core-rs/             ║   ║  skills/hermes/       ║
║  sdks/typescript/     ║   ║  cynepic-guardian     ║   ║  obsidian_vault/      ║
║                       ║   ║                       ║   ║                       ║
║  Tracer + Client      ║   ║  Policy parser        ║   ║  Schema-typed ingest  ║
║  emit events          ║   ║  Circuit breaker      ║   ║  Idempotent cache     ║
║  Swallows transport   ║   ║  PASS/FAIL/ESCALATE   ║   ║  Markdown sessions    ║
║  failures so it       ║   ║  Microsecond latency  ║   ║  Pluggable reflection ║
║  cannot break the     ║   ║  No unwrap in prod    ║   ║                       ║
║  host agent           ║   ║                       ║   ║                       ║
╚═══════════════════════╝   ╚═══════════════════════╝   ╚═══════════════════════╝
        SDKs                       Rust core                   Hermes + Obsidian
```

### 1. Instrument (Phase 2 — shipped)
SDKs sit inside each agent process. Calls to LLMs and tools are wrapped
in a `Tracer.tool_call(...)` / `tracer.toolCall(...)` block; the SDK
emits typed `AgentTraceEvent` records and forwards them to a collector.
The transport is pluggable (`httpx.MockTransport`, custom `fetch`) so
tests run without network. Emit failures are logged and swallowed — the
host agent never goes down because TrustLayer is sick.

### 2. Evaluate (Phase 4 — shipped)
The Rust core (`core-rs/`) hosts the `cynepic-guardian` circuit breaker
and the JSON-based CSL policy language. The guardian receives an
`AgentTraceEvent` (typically a `TOOL_CALL` or `LLM_CALL`) and returns a
`Decision` of `PASS`, `FAIL`, or `ESCALATE` together with the rule that
matched. Ships today as an Axum HTTP sidecar (`trustlayer-guardian`);
in-process FFI is a future optimisation. Cynefin-aware default: events
classified `CHAOTIC` escalate by default when no rule matches.

### 3. Reflect (Phase 3 — shipped)
Hermes consumes the trace stream asynchronously and materialises it as
human-readable markdown in an Obsidian vault. Each
`(agent_id, session_id)` becomes one note in `03_Memory_Traces/`. A
periodic reflection pass produces dated synthesis notes in
`05_Reflections/` that link back via Obsidian wikilinks. Hermes is
memory- and token-bounded by design (see [ADR-003] in
`obsidian_vault/01_Architecture/`).

## Data flow today

```
                          ┌────────────────────────────┐
agent process ──SDK──>    │  cynepic-guardian (HTTP)   │  ──> PASS / FAIL / ESCALATE
       │                  │  core-rs/trustlayer-guardian│
       │                  └────────────────────────────┘
       │
       └── all events ──> [JSONL tee] ──> Hermes ──> Obsidian vault
                                              │
                                              ├─> .hermes_state/   (sidecar JSONL, runtime only)
                                              ├─> 03_Memory_Traces/ (session notes)
                                              └─> 05_Reflections/   (synthesis notes)
```

- The SDK calls `GuardianClient.check(event)` synchronously before
  invoking a sensitive tool. The guardian is fail-open by default so
  instrumentation cannot make the host agent unavailable.
- The same event flows to Hermes regardless of the verdict — the
  verdict itself is recorded as a `POLICY_CHECK` event.
- Until a dedicated collector ships, the practical pattern is: SDK
  emits to a local JSONL file (or mock transport in tests); a batch
  job pipes the JSONL into `python -m hermes.cli`.

## Future optimisations (not blocking)

- **FFI embedding** of the Rust guardian directly in Python (via
  `pyo3`) to drop the ~100µs HTTP cost.
- **A dedicated collector service** that consumes events from many
  agent processes and feeds both Hermes and the long-term store.
- **TypeScript guardian client** for parity (Phase 4.5).

## ADRs

The "why" behind each layer is recorded in
`obsidian_vault/01_Architecture/`:

- **ADR-001 — SDK Wedge** (Phase 2, accepted)
- **ADR-002 — Hermes Memory Agent** (Phase 3, accepted)
- **ADR-003 — Hermes context / token / memory model** (Phase 3.5, accepted)
- **ADR-004 — cynepic-guardian + policy language** (Phase 4, accepted)

## Non-goals (for now)
- A bespoke time-series database — JSONL + Obsidian is enough for the
  observability/governance wedge. Telemetry sinks can be added later.
- A new agent framework — TrustLayer instruments existing frameworks
  (LangChain, CrewAI, custom). It does not replace them.
- A hosted SaaS — the design is self-hostable end-to-end. A managed
  control plane can sit on top later.
