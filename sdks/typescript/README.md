# @trustlayer/sdk (TypeScript)

TypeScript / JavaScript SDK for the TrustLayer protocol — emit
[`AgentTraceEvent`](../../spec/v0.1/01-wire-format.md)s, gate tool
calls with the [`cynepic-guardian`](../../core-rs/). Apache-2.0.

- **Wire-format conformance:** [v0.1 W1–W7](../../spec/v0.1/06-conformance.md)
- **Requires:** Node 18+ (uses native `fetch`, `AbortController`, `crypto.randomUUID`)
- **Hard deps:** `zod`
- **Strict mode:** `strict: true`, `noUncheckedIndexedAccess: true`

See the root [README](../../README.md) for the full architecture and
the [`spec/v0.1/`](../../spec/v0.1/) directory for the citable protocol.

## Install

```bash
# From the repo:
cd sdks/typescript
npm install
npm run build         # tsc to dist/

# Test + typecheck:
npm test              # 33 vitest cases
npm run typecheck     # tsc --noEmit
```

When `@trustlayer/sdk` is on npm (pre-1.0 release pending) the end-user
install will be `npm install @trustlayer/sdk`.

## Quickstart

### Instrument a tool call

```ts
import { Tracer } from "@trustlayer/sdk";

const tracer = new Tracer({ agentId: "researcher-1", sessionId: "S1" });

const answer = await tracer.toolCall(
  "web.search",
  { q: "trustlayer" },
  () => runSearch("trustlayer"),
);
```

Emits a `TOOL_CALL` before the callback runs and a `TOOL_RESULT`
after (with `metrics.latency_ms`). On rejection / throw, the
`TOOL_RESULT` carries the error in `payload.error` and the original
error is re-thrown.

### Wrap a function once

```ts
import { Tracer, wrapTool } from "@trustlayer/sdk";

const tracer = new Tracer({ agentId: "researcher-1" });
const search = wrapTool(tracer, "web.search", (q: string) => runSearch(q));

await search("trustlayer");   // every call emits TOOL_CALL + TOOL_RESULT
```

### Gate before invoking (guardian-aware)

```ts
import { GuardianClient, Tracer } from "@trustlayer/sdk";

const tracer   = new Tracer({ agentId: "researcher-1", sessionId: "S1" });
const guardian = new GuardianClient({ policyName: "default" });

const verdict = await tracer.check(
  "external_llm",
  { prompt: "summarise report", model: "gpt-4" },
  { guardian, policyName: "default" },
);

if (verdict.decision !== "PASS") {
  throw new Error(`blocked by ${verdict.rule}: ${verdict.reason}`);
}
const result = await callExternalLlm(...);
```

`Tracer.check()` emits the candidate `TOOL_CALL`, asks the guardian,
and emits a `POLICY_CHECK` carrying the verdict — both events share
a `trace_id` so the trace stream correlates the action with the
decision.

## Public API

### `TrustLayerClient`

Fetch-based client that POSTs `AgentTraceEvent`s to a TrustLayer
ingest endpoint. Failures are surfaced via `onError` and **swallowed**
into the caller's promise — instrumentation must never take down the
host agent.

```ts
import { TrustLayerClient } from "@trustlayer/sdk";

const client = new TrustLayerClient({
  endpoint: "http://127.0.0.1:8089/v1/events",  // default
  apiKey: undefined,                            // falls back to env
  fetch: globalThis.fetch,                      // injectable for tests
  timeoutMs: 5000,
  onError: (err) => console.warn("[trustlayer]", err),
});

await client.emit(event);
await client.emitBatch([e1, e2]);
```

### `GuardianClient`

Fetch-based client for `POST /v1/check`. **Fail-open by default**: on
transport / parse error returns a synthetic `policy: "fallback"`
verdict whose `decision` is `"PASS"`. Pass `failOpen: false` for hard
denial.

```ts
import { GuardianClient } from "@trustlayer/sdk";

const guardian = new GuardianClient({
  endpoint: "http://127.0.0.1:8089/v1/check",   // default
  policyName: "default",
  apiKey: undefined,                            // falls back to env
  timeoutMs: 1000,
  failOpen: true,
});

const verdict = await guardian.check(event, "default");
// verdict: { decision, rule, reason, policy }
```

### `Tracer`

Bind an `(agentId, sessionId)` and emit typed events through a shared
`TrustLayerClient`:

```ts
new Tracer({
  agentId: string;
  sessionId?: string;          // uuid v4 if omitted (via crypto.randomUUID)
  client?: TrustLayerClient;   // default constructor if omitted
  cynefinDomain?: CynefinDomain;  // default "DISORDER"
});
```

Methods: `.emit(...)`, `.toolCall(...)`, `.policyCheck(...)`,
`.check(...)`, `.buildEvent(...)`.

### `wrapTool`

Wraps any sync or async function so each call emits `TOOL_CALL` +
`TOOL_RESULT` through the supplied tracer. Returns an async function
even if the wrapped function is sync.

```ts
const search = wrapTool(tracer, "web.search", (q: string) => runSearch(q));
```

## Configuration

| Env var | Effect |
|---|---|
| `TRUSTLAYER_API_TOKEN` (Node) | Fallback bearer token for both clients. |
| `VITE_TRUSTLAYER_API_TOKEN` (Vite build) | Same, for browser-bundled clients (e.g. the dashboard). |

The bearer-token resolution order is:

1. Explicit `apiKey` option (always wins).
2. `TRUSTLAYER_API_TOKEN` via `process.env` (Node).
3. `VITE_TRUSTLAYER_API_TOKEN` via `import.meta.env` (Vite-built bundles).
4. Undefined → no `Authorization` header is sent.

This matches the [ADR-007](../../obsidian_vault/01_Architecture/ADR-007-Auth-Bearer-Token.md)
sidecar gate: set the token in the sidecar and every agent / dashboard
picks it up automatically via the same env name.

## Tests

```bash
npm test                # 33 vitest cases (schema, client, guardian, tracer)
npm run typecheck       # tsc --noEmit
```

## Examples

- [`examples/agent.ts`](./examples/agent.ts) — minimal agent loop instrumented with the SDK.

## Links

- [Root README](../../README.md) — full architecture, deployment, KPI playbook.
- [v0.1 specification](../../spec/v0.1/) — the citable protocol.
- [Conformance checklist](../../spec/v0.1/06-conformance.md) — what this SDK satisfies (W1–W7).
- [Versioning policy](../../docs/VERSIONING.md).
- [Contributing](../../CONTRIBUTING.md).
