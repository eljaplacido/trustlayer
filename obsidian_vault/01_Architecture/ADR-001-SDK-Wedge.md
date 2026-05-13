---
adr: 001
status: accepted
date: 2026-05-07
tags: [architecture, sdk, observability, schema]
---

# ADR-001 — SDK Wedge: Python + TypeScript Tracing Clients

## Context
TrustLayer's value depends on capturing high-fidelity agent traces at the
point of instrumentation. The Rust core (Phase 4) and Hermes memory agent
(Phase 3) both consume the same wire format, so we need both Python and
TypeScript SDKs that emit identical events well before the collector or
policy engine exist.

## Decision
- **Wire format owner:** `docs/SCHEMA.md` is the source of truth. The
  Pydantic models in `sdks/python/src/trustlayer/schema.py` and the Zod
  schemas in `sdks/typescript/src/schema.ts` mirror it byte-for-byte.
  Drift is caught by the cross-SDK tests that round-trip the same JSON.
- **Transport pluggability:** both clients accept an injected transport
  (httpx `BaseTransport`, or a `fetch` impl) so tests run without a network
  and so users can plug in their own batching/queueing.
- **Failure mode:** emit failures are logged and swallowed. Instrumentation
  must never take down the host agent. This is enforced by tests that
  return HTTP 500 / throw network errors and assert `emit()` resolves.
- **Tracer ergonomics:** Python uses a context manager
  (`with tracer.tool_call(...) as out: out["value"] = ...`) and TypeScript
  uses a higher-order callback (`tracer.toolCall(name, args, () => ...)`).
  Both surface a `latency_ms` automatically. Decorators / `wrapTool`
  layer on top for the common "wrap a function" case.
- **No async Python yet.** A future ADR will introduce an `AsyncTracer`
  if/when we hit a use case that warrants it; the current sync client is
  enough for LangChain-style agents and keeps the wedge minimal.

## Consequences
- Hermes (Phase 3) can be implemented against the schema models directly
  by importing `trustlayer.schema`; it does not need to re-derive types.
- The Rust core (Phase 4) can ingest the same JSON without per-SDK
  branching.
- The `cynefin_domain` enum is already plumbed end-to-end so the policy
  engine can be added without an SDK migration.

## Links
- Schema: [[../../docs/SCHEMA.md]]
- Architecture: [[../../docs/ARCHITECTURE.md]]
- Status: [[../../docs/CURRENT_STATUS.md]]
- Hermes manifest: [[../02_Agent_Skills/Hermes_Manifest.md]]
