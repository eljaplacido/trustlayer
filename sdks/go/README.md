# trustlayer (Go)

Go SDK for the TrustLayer protocol — emit
[`AgentTraceEvent`](../../spec/v0.1/01-wire-format.md)s, gate tool
calls with the [`cynepic-guardian`](../../core-rs/). Apache-2.0.

- **Module:** `github.com/eljaplacido/trustlayer/sdks/go`
- **Import path:** `github.com/eljaplacido/trustlayer/sdks/go/trustlayer`
- **Wire-format conformance:** [v0.1 W1–W7](../../spec/v0.1/06-conformance.md)
- **Requires:** Go 1.22+
- **Deps:** stdlib + `github.com/google/uuid`. No HTTP framework, no logging dep, no test framework beyond `testing` + `httptest`.

See the root [README](../../README.md) for the full architecture and
the [`spec/v0.1/`](../../spec/v0.1/) directory for the citable
protocol. Design rationale lives in
[ADR-011](../../obsidian_vault/01_Architecture/ADR-011-Go-SDK.md).

## Install

```bash
# In an external project, once tagged:
go get github.com/eljaplacido/trustlayer/sdks/go@latest

# From the repo (for local development):
cd sdks/go
go test ./...
go build ./examples/...
```

## Quickstart

### Instrument a tool call

```go
import "github.com/eljaplacido/trustlayer/sdks/go/trustlayer"

client, _ := trustlayer.NewClient(trustlayer.ClientOptions{})
defer client.Close()

tracer := trustlayer.NewTracer(client, "researcher-1", "S1")

var result any
var err error
done := tracer.ToolCall(ctx, "web.search",
    map[string]any{"q": "trustlayer"}, &result, &err)
defer done()

result, err = runSearch("trustlayer")
```

Emits a `TOOL_CALL` immediately and a `TOOL_RESULT` when `done()`
fires — typically via `defer`. Captures result, error, and latency
into the result event automatically.

### Gate before invoking (guardian-aware)

```go
client, _   := trustlayer.NewClient(trustlayer.ClientOptions{})
guardian, _ := trustlayer.NewGuardian(trustlayer.GuardianOptions{
    PolicyName: "default",
})
tracer := trustlayer.NewTracer(client, "researcher-1", "S1")

verdict, _ := tracer.Check(ctx, "external_llm",
    map[string]any{"prompt": "summarise report", "model": "gpt-4"},
    &trustlayer.TracerCheck{Guardian: guardian, PolicyName: "default"},
)

switch verdict.Decision {
case trustlayer.DecisionPass:
    result := callExternalLLM(...)
case trustlayer.DecisionFail:
    return fmt.Errorf("blocked: %s", *verdict.Reason)
case trustlayer.DecisionEscalate:
    notifyOnCall(verdict)
}
```

`Tracer.Check` emits the candidate `TOOL_CALL`, asks the guardian,
and emits a `POLICY_CHECK` carrying the verdict — both events share
a `trace_id` so the trace stream correlates the action with the
decision.

## Public API

### `TrustLayerClient`

Goroutine-safe ingest client. Transport-layer errors are returned (so
the caller can log them) but **must not** propagate into agent
control flow.

```go
client, err := trustlayer.NewClient(trustlayer.ClientOptions{
    Endpoint:   "http://127.0.0.1:8089/v1/events",  // default
    APIKey:     "",                                 // falls back to env
    HTTPClient: nil,                                // default 5s timeout
})

err = client.Emit(ctx, event)
err = client.EmitBatch(ctx, []trustlayer.AgentTraceEvent{e1, e2})
client.Close()
```

### `GuardianClient`

Goroutine-safe guardian client. **Fail-open by default**: on
transport / parse error returns a synthetic
`Policy: "fallback"` verdict whose `Decision` is `PASS`. Pass
`FailOpen: &false` for hard denial.

```go
g, err := trustlayer.NewGuardian(trustlayer.GuardianOptions{
    Endpoint:   "http://127.0.0.1:8089/v1/check",   // default
    PolicyName: "default",
    APIKey:     "",                                 // falls back to env
    HTTPClient: nil,                                // default 1s timeout
    FailOpen:   nil,                                // nil = true
})

verdict, _ := g.Check(ctx, event)
verdict, _ = g.CheckWithPolicy(ctx, event, "ad-hoc")
```

The error return is **always `nil`** — instrumentation never
propagates guardian failures as fatal. Use `verdict.Policy ==
"fallback"` and `verdict.Reason` to log degraded paths.

### `Tracer`

```go
tracer := trustlayer.NewTracer(client, "researcher-1", "S1")
tracer.Emit(ctx, event)
tracer.ToolCall(ctx, name, args, &result, &err)  // returns a deferable closer
tracer.Check(ctx, toolName, toolArgs, &trustlayer.TracerCheck{...})
```

### `NewEvent` + options

```go
ev := trustlayer.NewEvent(
    "researcher-1", "S1", trustlayer.EventToolCall,
    trustlayer.WithPayload(map[string]any{"tool_name": "calc"}),
    trustlayer.WithCynefin(trustlayer.CynefinComplex),
    trustlayer.WithMetrics(trustlayer.Metrics{LatencyMs: &lat}),
)
```

Each `NewEvent` produces a fresh UUID v4 `trace_id` and a UTC
timestamp.

### Strict envelope (W1 conformance)

`AgentTraceEvent.UnmarshalJSON` rejects unknown top-level fields and
unknown enum values. This matches Pydantic `extra="forbid"`, Zod
`.strict()`, and serde `deny_unknown_fields`. A cross-language test
in `core-rs/tests/cross_language.rs` parses a Go-emitted fixture and
asserts round-trip parity.

## Configuration

| Env var | Effect |
|---|---|
| `TRUSTLAYER_API_TOKEN` | Fallback bearer token for both clients. |

Token resolution order: explicit `APIKey` field → `TRUSTLAYER_API_TOKEN`
env var → none. Matches [ADR-007](../../obsidian_vault/01_Architecture/ADR-007-Auth-Bearer-Token.md).

## Tests

```bash
go vet ./...
go test ./...                # 31 cases (9 schema + 7 client + 9 guardian + 6 tracer)
go build ./examples/...
```

## Examples

- [`examples/conformance/`](./examples/conformance/main.go) — deterministic fixture generator. Emits one canonical `AgentTraceEvent` and pretty-prints it. The Rust core's cross-language test loads its output as `spec/v0.1/fixtures/event-canonical-go.json`.
- [`examples/end_to_end_demo/`](./examples/end_to_end_demo/main.go) — boots in-process fake guardian + ingest servers and walks `Tracer.Check` through PASS / FAIL / ESCALATE scenarios. Run with `go run ./examples/end_to_end_demo`.

## Idioms

- Every public method takes `context.Context` first.
- `Tracer.ToolCall` returns a closer rather than wrapping a callback — Go idiom is `defer done()`. Pass `*result` and `*err` pointers; the closer reads them at defer time.
- All clients are goroutine-safe.
- `Close()` is a no-op today but kept for API symmetry with the Python / TypeScript SDKs and future pooled resources.

## Links

- [Root README](../../README.md) — full architecture, deployment, KPI playbook.
- [v0.1 specification](../../spec/v0.1/) — the citable protocol.
- [Conformance checklist](../../spec/v0.1/06-conformance.md) — what this SDK satisfies (W1–W7).
- [ADR-011](../../obsidian_vault/01_Architecture/ADR-011-Go-SDK.md) — design rationale.
- [Contributing](../../CONTRIBUTING.md).
