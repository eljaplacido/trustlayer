# TrustLayer

**Open governance, observability, and trust for agentic AI.**

TrustLayer is a self-hostable middleware and observability plane for
multi-agent systems. You instrument your agents through a small SDK
(Python, TypeScript, Go, or any HTTP client), point them at a Rust
sidecar, and get:

- a **policy engine** that adjudicates every tool call against a
  declarative ruleset (`PASS` / `FAIL` / `ESCALATE`),
- an **append-only trace store** that records every `AgentTraceEvent`,
- a **dashboard** with four live panes (Traces, Sessions, Reflections,
  Policy),
- a **memory subagent** that materialises sessions into a navigable
  Obsidian vault and runs recursive reflections,
- an **MCP server** that exposes the whole surface to any MCP-aware
  agent (Claude Code, MCP Inspector, frameworks),
- a **Prometheus `/metrics` endpoint** with verdict counts, latency
  histograms, and ingest volume,
- a **bridge to OpenTelemetry** that ships events into any existing
  OTel pipeline (OTLP, Jaeger, Tempo, Honeycomb, Grafana, Datadog).

No SaaS account. No telemetry leaking offsite. Apache-2.0. Four
reference SDKs, one wire format, 297 tests in CI.

The wire format is a versioned, RFC-2119 specification at
[`spec/v0.1/`](./spec/v0.1/) — designed so anyone can write their own
conforming implementation.

---

## Table of contents

1. [Who is this for](#who-is-this-for)
2. [Use cases](#use-cases)
3. [Five-minute quickstart](#five-minute-quickstart)
4. [How it fits together](#how-it-fits-together)
5. [Integration patterns](#integration-patterns)
   - [Python](#python)
   - [TypeScript / Node](#typescript--node)
   - [Go](#go)
   - [Any language (raw HTTP)](#any-language-raw-http)
6. [Policy engine](#policy-engine)
7. [Deployment](#deployment)
8. [Observability & KPIs](#observability--kpis)
9. [Memory & reflections (Hermes)](#memory--reflections-hermes)
10. [MCP integration](#mcp-integration)
11. [The protocol](#the-protocol)
12. [Configuration reference](#configuration-reference)
13. [Status & roadmap](#status--roadmap)
14. [Contributing](#contributing)
15. [License](#license)

---

## Who is this for

You're building or operating systems where LLM-driven agents call
tools, invoke models, and act on real resources. You want:

- A **policy plane** that can refuse or escalate tool calls without
  rewriting the agent code each time you change rules.
- A **trace plane** you can audit, replay, and feed into your existing
  observability stack.
- A **deployment story** you control end-to-end — one binary, one
  policy file, one ingest URL. No external dependency.

If you've outgrown print-debugging your agent but you're not yet
running a managed agentic platform, this is the layer between.

## Use cases

**Production guardrails for a tool-using agent.** Block calls to
`external_llm` when the prompt contains PII. Block `shell` calls
outside an allowlist. Escalate any tool invocation in a `CHAOTIC`
Cynefin context to a human reviewer. Hot-reload the policy file when
you want to tighten rules without restarting agents.

**Auditable agent runs.** Every `TOOL_CALL`, `TOOL_RESULT`,
`LLM_CALL`, `POLICY_CHECK`, and human escalation is an
`AgentTraceEvent` with a `trace_id`, timestamps, and cost/latency
metrics. The trace store keeps an append-only JSONL log; the dashboard
gives a live read of it; Hermes turns it into per-session markdown
notes for human review.

**OTel-stack interop.** If you already run Tempo / Jaeger / Datadog
/ Grafana via OTLP, the `trustlayer.otel` bridge ships every event
into your pipeline as an OTel span — no second backend, no parallel
collector.

**Multi-agent visibility.** One sidecar collects traces from many
agents (any language) keyed by `agent_id` + `session_id`. The
dashboard's Sessions pane shows one row per session, drill-down per
event. Useful when you've got LangGraph + a Go orchestrator + a
TypeScript front-end agent all talking to one workflow.

**Spec-conformant SDK in a new language.** TrustLayer ships first-party
SDKs in four languages; the wire format is documented to RFC-2119
precision so anyone can write a fifth. The spec has a normative
conformance section (W1–H6) and a fixture directory.

---

## Five-minute quickstart

### 1. Run the sidecar

```bash
git clone https://github.com/eljaplacido/trustlayer.git
cd trustlayer/core-rs
cargo run --release --features server --bin trustlayer-guardian
```

The sidecar binds `127.0.0.1:8089` and exposes:

- `POST /v1/check` — policy adjudication
- `POST /v1/events` / `GET /v1/events` — trace store ingest + read
- `GET /v1/sessions` and `/v1/sessions/{agent}/{session}` — session
  summaries and drill-down
- `GET /metrics` — Prometheus exposition
- `GET /healthz` — liveness

It loads `core-rs/policies/default.json` and watches it for changes
(hot-reload).

### 2. Instrument an agent (Python)

```bash
cd ../sdks/python
pip install -e .
```

```python
from trustlayer import Tracer, GuardianClient

tracer   = Tracer(agent_id="researcher-1", session_id="S1")
guardian = GuardianClient(policy_name="default")

verdict = tracer.check(
    "external_llm",
    {"prompt": "summarise this report"},
    guardian=guardian,
)

if verdict["decision"] == "PASS":
    answer = call_external_llm(...)
else:
    print(f"blocked: {verdict['rule']} - {verdict['reason']}")
```

`tracer.check(...)` does three things atomically: emits a `TOOL_CALL`
event, asks the guardian, emits a `POLICY_CHECK` event carrying the
verdict (the two events share a `trace_id` so you can correlate them).
You decide whether to actually invoke the tool.

### 3. Watch it happen

```bash
cd ../../dashboard
npm install && npm run dev   # http://localhost:5173
```

Four panes:

- **Traces** — live `AgentTraceEvent` stream (`GET /v1/events`)
- **Sessions** — one row per `(agent_id, session_id)`; click for the
  full timeline
- **Reflections** — Hermes synthesis notes
- **Policy** — recent `POLICY_CHECK` events with PASS / FAIL /
  ESCALATE chips

### 4. Scrape the metrics

```bash
curl -s http://127.0.0.1:8089/metrics | grep ^trustlayer_
# trustlayer_check_total{decision="PASS"} 12
# trustlayer_check_total{decision="FAIL"} 1
# trustlayer_events_ingested_total 47
# trustlayer_requests_total{route="/v1/check",status="200"} 13
# ...
```

---

## How it fits together

TrustLayer is four loosely-coupled layers around one canonical wire
format (the `AgentTraceEvent`):

```
                       agent process (any language)
                                │
            ┌───────────────────┼───────────────────┐
            │ SDK call          │ SDK call           │
            ▼                   ▼                    ▼
       Tracer.check()      Tracer.tool_call()    direct emit
            │                   │                    │
            └──── HTTP ─────────┴─────── HTTP ───────┘
                                │
                  ┌─────────────▼──────────────┐
                  │   trustlayer-guardian       │
                  │   (Rust sidecar)            │
                  │                             │
                  │   • POST /v1/check          │  ──> PASS / FAIL / ESCALATE
                  │   • POST /v1/events         │  ──> append-only JSONL
                  │   • GET  /v1/events,        │
                  │          /v1/sessions,      │
                  │          /v1/reflections    │
                  │   • GET  /metrics, /healthz │
                  └──────┬──────────────────┬───┘
                         │                  │
                ┌────────▼────────┐ ┌───────▼───────────────┐
                │ Dashboard       │ │ Hermes memory subagent │
                │ (React + Vite)  │ │ Obsidian vault writer  │
                └─────────────────┘ │ + recursive reflector  │
                                    └────────────────────────┘

   MCP-aware agents ──stdio / SSE──▶  mcp-server  ──▶  SDK + Guardian + Hermes
```

The wire format (`AgentTraceEvent`) is **the contract**. The Rust,
Python, TypeScript, and Go implementations all serialise to the same
bytes; a cross-language test fixture proves it on every push.

The four layers:

1. **Instrument** — SDKs build typed `AgentTraceEvent`s and ship them
   to the sidecar.
2. **Evaluate** — the Rust sidecar adjudicates each event against a
   declarative policy (CSL) and returns a verdict.
3. **Reflect** — Hermes materialises sessions into Obsidian markdown
   and runs structural (or LLM-backed) reflections.
4. **Observe** — the dashboard, `/metrics`, and trace-store reads
   surface everything to humans and other systems.

Full architecture write-up: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).

---

## Integration patterns

### Python

```bash
pip install -e sdks/python              # base SDK
pip install -e sdks/python[otel]        # + OTel bridge (optional)
```

#### Pattern A — Context-managed tool spans

Wrap any tool call in a span. `TOOL_CALL` is emitted on entry,
`TOOL_RESULT` on exit (or on exception) with the latency.

```python
from trustlayer import Tracer

tracer = Tracer(agent_id="researcher-1", session_id="S1")

with tracer.tool_call("web.search", {"q": "trustlayer"}) as out:
    out["value"] = run_search("trustlayer")
```

#### Pattern B — Decorator

```python
from trustlayer import Tracer, instrument_tool

tracer = Tracer(agent_id="researcher-1")

@instrument_tool(tracer, tool_name="web.search")
def search(query: str) -> list[str]:
    return run_search(query)

search("trustlayer")  # automatically emits TOOL_CALL + TOOL_RESULT
```

#### Pattern C — Gate before invoking

`Tracer.check()` asks the guardian and emits both a `TOOL_CALL` and a
`POLICY_CHECK` (sharing one `trace_id`) so the trace stream records
both the candidate and the decision.

```python
from trustlayer import Tracer, GuardianClient

tracer   = Tracer(agent_id="researcher-1", session_id="S1")
guardian = GuardianClient(policy_name="default")

verdict = tracer.check(
    "external_llm",
    {"prompt": "summarise report", "model": "gpt-4"},
    guardian=guardian,
)

match verdict["decision"]:
    case "PASS":
        result = call_external_llm(...)
    case "FAIL":
        raise PermissionError(verdict["reason"])
    case "ESCALATE":
        notify_oncall(verdict)
```

#### Pattern D — Bridge to OpenTelemetry

```python
from opentelemetry import trace as otel_trace
from trustlayer.otel import OTelExporter

# Caller wires up TracerProvider + their exporter of choice
# (OTLP, Jaeger, Zipkin, Console, ...) as usual.
exporter = OTelExporter(tracer=otel_trace.get_tracer("my-agent"))
exporter.emit(event)            # one OTel span per AgentTraceEvent
exporter.emit_batch([e1, e2])
```

Attribute naming: `trustlayer.{trace_id, agent_id, session_id,
event_type, cynefin_domain}`, `trustlayer.payload.<dotted-path>`,
`trustlayer.metrics.<key>`. See
[ADR-012](./obsidian_vault/01_Architecture/ADR-012-OpenTelemetry-Exporter.md).

A runnable demo:
[`sdks/python/examples/otel_exporter_demo.py`](./sdks/python/examples/otel_exporter_demo.py).

### TypeScript / Node

```bash
cd sdks/typescript && npm install
```

#### Pattern A — Tool callback

```ts
import { Tracer } from "@trustlayer/sdk";

const tracer = new Tracer({ agentId: "researcher-1", sessionId: "S1" });

const answer = await tracer.toolCall(
  "web.search",
  { q: "trustlayer" },
  () => runSearch("trustlayer"),
);
```

#### Pattern B — Wrap a function once

```ts
import { Tracer, wrapTool } from "@trustlayer/sdk";

const tracer = new Tracer({ agentId: "researcher-1" });
const search = wrapTool(tracer, "web.search", (q: string) => runSearch(q));

await search("trustlayer");   // emits TOOL_CALL + TOOL_RESULT
```

#### Pattern C — Gate before invoking

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
  // verdict.rule, verdict.reason, verdict.policy
  throw new Error(`blocked by ${verdict.rule}: ${verdict.reason}`);
}
```

### Go

```bash
cd sdks/go && go test ./...
```

```go
import "github.com/eljaplacido/trustlayer/sdks/go/trustlayer"

client, _   := trustlayer.NewClient(trustlayer.ClientOptions{})
guardian, _ := trustlayer.NewGuardian(trustlayer.GuardianOptions{
    PolicyName: "default",
})
tracer := trustlayer.NewTracer(client, "researcher-1", "S1")

verdict, _ := tracer.Check(ctx, "external_llm",
    map[string]any{"prompt": "hi"},
    &trustlayer.TracerCheck{Guardian: guardian, PolicyName: "default"},
)
// verdict.Decision is "PASS" | "FAIL" | "ESCALATE"
```

For tool spans use the closure-on-defer pattern:

```go
var result any
var err error
done := tracer.ToolCall(ctx, "web.search",
    map[string]any{"q": "trustlayer"}, &result, &err)
defer done()
result, err = runSearch("trustlayer")
```

End-to-end walkthrough (PASS / FAIL / ESCALATE against an in-process
fake sidecar): [`sdks/go/examples/end_to_end_demo`](./sdks/go/examples/end_to_end_demo/main.go).

### Any language (raw HTTP)

The wire format is JSON and the only required call is `POST /v1/check`
or `POST /v1/events`:

```bash
curl -X POST http://127.0.0.1:8089/v1/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TRUSTLAYER_API_TOKEN" \
  -d '{
    "trace_id":   "11111111-1111-4111-8111-111111111111",
    "agent_id":   "researcher-1",
    "session_id": "S1",
    "timestamp":  "2026-05-25T10:00:00+00:00",
    "event_type": "TOOL_CALL",
    "payload": { "tool_name": "external_llm", "model": "gpt-4" }
  }'
```

`spec/v0.1/01-wire-format.md` is the citable reference. A new SDK
counts as conformant if it passes the W1–W7 checklist in
`spec/v0.1/06-conformance.md`.

---

## Policy engine

Policies are JSON files: a `name` plus an **ordered** list of rules.
The guardian walks rules top-to-bottom and returns the first match.

```json
{
  "name": "default",
  "rules": [
    {
      "name": "block_external_llm_for_pii_tools",
      "match": {
        "event_type": "TOOL_CALL",
        "tool_name":  "external_llm"
      },
      "decision": "FAIL",
      "reason":   "External LLM is disabled in this policy."
    },
    {
      "name": "block_gpt4_via_payload_predicate",
      "match": {
        "event_type": "LLM_CALL",
        "payload":    { "model": "gpt-4" }
      },
      "decision": "FAIL",
      "reason": "GPT-4 calls require explicit allow-list."
    },
    {
      "name": "escalate_complex_human_calls",
      "match": {
        "event_type":     "TOOL_CALL",
        "cynefin_domain": "COMPLEX",
        "tool_name":      "human_callout"
      },
      "decision": "ESCALATE",
      "reason": "Complex-domain human callouts require oncall review."
    },
    {
      "name": "allow_calculator",
      "match": {
        "event_type": "TOOL_CALL",
        "tool_name":  "calculator"
      },
      "decision": "PASS"
    }
  ]
}
```

**`match` fields:**

- `event_type` — one of the seven `event_type` enum values.
- `tool_name` — shortcut for `payload.tool_name` equality.
- `agent_id` — scope the rule to one agent.
- `cynefin_domain` — match the event's domain classification.
- `payload` — a map of **dotted-path → JSON literal**, deep-equality,
  AND across keys. See [spec §4.3](./spec/v0.1/04-policy-language.md#43-payload-predicates).

Default behaviour when no rule matches:

- `cynefin_domain == "CHAOTIC"` → `ESCALATE` (Cynefin-aware default).
- Otherwise → `PASS`.

**Hot reload:** the sidecar watches the policy file. Edit it on disk
and the next `/v1/check` sees the new policy. A failed parse logs a
warning and keeps the live policy in place (configurable via
`TRUSTLAYER_POLICY_RELOAD=false`).

---

## Deployment

### Local development

```bash
# Terminal 1 — sidecar
cd core-rs
cargo run --release --features server --bin trustlayer-guardian

# Terminal 2 — dashboard
cd dashboard && npm install && npm run dev
```

Defaults: sidecar on `127.0.0.1:8089`, dashboard on
`http://localhost:5173`, policy from `core-rs/policies/default.json`,
events appended to `core-rs/events.jsonl`.

### Single host with auth and persistence

```bash
export TRUSTLAYER_API_TOKEN=$(openssl rand -hex 32)
export TRUSTLAYER_BIND=0.0.0.0:8089
export TRUSTLAYER_POLICY=/etc/trustlayer/policy.json
export TRUSTLAYER_EVENTS_PATH=/var/lib/trustlayer/events.jsonl
export TRUSTLAYER_VAULT_PATH=/var/lib/trustlayer/vault
export TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC=200

trustlayer-guardian
```

Agents pick the token up automatically:

```bash
export TRUSTLAYER_API_TOKEN=…   # same token, on every agent host
```

The SDKs (Python, TypeScript, Go) read this env var by default; you
don't need to thread it through the client constructor.

### Docker (sketch)

A minimal `Dockerfile` for the sidecar:

```dockerfile
FROM rust:1.94 AS build
WORKDIR /src
COPY core-rs /src/core-rs
RUN cd core-rs && cargo build --release --features server --bin trustlayer-guardian

FROM debian:bookworm-slim
COPY --from=build /src/core-rs/target/release/trustlayer-guardian /usr/local/bin/
COPY core-rs/policies/default.json /etc/trustlayer/policy.json
ENV TRUSTLAYER_POLICY=/etc/trustlayer/policy.json \
    TRUSTLAYER_BIND=0.0.0.0:8089
EXPOSE 8089
CMD ["trustlayer-guardian"]
```

A `docker-compose.yml` is on the roadmap and will land alongside the
v0.1 publication.

### Hot-reload a policy in production

```bash
# Operator workflow — no restart required.
vim /etc/trustlayer/policy.json
# Save. The sidecar's notify watcher picks up the change within
# ~200ms, parses it, and atomically swaps in the new policy.
```

Bad-parse safety: the live policy stays in place if the new file
doesn't parse. Watch the sidecar logs for `policy reloaded:` /
`policy reload from … failed:`.

---

## Observability & KPIs

### What `/metrics` exposes

```
trustlayer_check_total{decision="PASS|FAIL|ESCALATE"}    counter
trustlayer_events_ingested_total                          counter
trustlayer_check_duration_seconds                         histogram
trustlayer_requests_total{route, status}                  counter
```

The verdict and request counters are pre-touched at zero so
dashboards work from cold start.

### Recommended KPIs and PromQL

| KPI | Why it matters | PromQL |
|---|---|---|
| **Policy fail rate** | Spikes mean tightening rules just blocked legitimate traffic, or a bad agent is in a loop. | `sum(rate(trustlayer_check_total{decision="FAIL"}[5m])) / sum(rate(trustlayer_check_total[5m]))` |
| **Escalation rate** | Every `ESCALATE` should map to a human queue. A non-zero rate without a queue is silent failure. | `sum(rate(trustlayer_check_total{decision="ESCALATE"}[5m]))` |
| **Verdict p95 latency** | The guardian sits on the hot path. p95 should stay under ~1ms locally; multi-ms means a slow rule or a sick host. | `histogram_quantile(0.95, sum by (le) (rate(trustlayer_check_duration_seconds_bucket[5m])))` |
| **Ingest throughput** | Capacity-planning the trace store. Pairs with the rate-limit env var. | `rate(trustlayer_events_ingested_total[5m])` |
| **Sidecar error rate** | Anything 5xx on the sidecar is your bug, not the agent's. | `sum(rate(trustlayer_requests_total{status=~"5.."}[5m])) by (route)` |
| **Rate-limit pressure** | Watch for sustained 429s — adjust `TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC` or shed load. | `sum(rate(trustlayer_requests_total{route="/v1/events",status="429"}[5m]))` |

### KPIs from the trace stream

These come out of the event payloads themselves, not `/metrics`:

| KPI | How |
|---|---|
| **Tokens per session** | `GET /v1/sessions/{agent}/{session}`, sum `metrics.tokens_prompt + tokens_completion` across events. |
| **Cost per session** | Same query, sum `metrics.cost_usd`. |
| **Tool mix per agent** | `GET /v1/events?agent_id=…` filtered to `event_type=TOOL_CALL`, group by `payload.tool_name`. |
| **First-time-blocked tools** | `event_type=POLICY_CHECK` filtered to `payload.result=FAIL`, group by `payload.action`. |

### Recommended alerts

- **Verdict latency p99 > 50ms for 5 min** — guardian is misbehaving;
  hot-reloaded a bad policy or hit a long match list.
- **`/healthz` failing for 30s** — sidecar is down.
- **Sustained `ESCALATE` rate with no operator action** — your
  oncall queue isn't actually being watched.
- **`/v1/events` 4xx rate > 1%** — an agent is emitting malformed
  envelopes; check SDK versions across the fleet.

### Dashboards

The bundled SPA at `dashboard/` gives a live human read on the same
data. Configure it to point at any sidecar URL:

```bash
echo 'VITE_TRUSTLAYER_BASE_URL=https://trustlayer.internal' \
  > dashboard/.env.local
echo 'VITE_TRUSTLAYER_API_TOKEN=…' >> dashboard/.env.local
cd dashboard && npm run build && npm run preview
```

For Grafana / Datadog / Honeycomb / Tempo, use the OpenTelemetry
bridge (see [Python pattern D](#pattern-d--bridge-to-opentelemetry))
or scrape `/metrics` directly.

---

## Memory & reflections (Hermes)

Hermes is a Python subagent that turns the trace stream into
human-readable Obsidian notes. It runs offline (no LLM required by
default) and produces:

- One markdown note per `(agent_id, session_id)` in
  `obsidian_vault/03_Memory_Traces/<agent>/<session>.md`.
- A dated synthesis note in `obsidian_vault/05_Reflections/`
  summarising tool counts, policy failures, latency totals, etc.

```bash
PYTHONPATH=skills python -m hermes.cli \
    --vault obsidian_vault \
    ingest traces.jsonl --reflect
```

You can also pull a static **code graph** into the vault (Hermes uses
[GitNexus](https://github.com/abhigyanpatwari/GitNexus) JSON output):

```bash
PYTHONPATH=skills python -m hermes.cli \
    --vault obsidian_vault \
    import-code-graph --gitnexus-root .gitnexus
```

Each function / class / file becomes one note under
`obsidian_vault/06_Code_Graph/<language>/` with `[[wikilink]]`
sections for Calls / Imports / Inherits / Contains. The dashboard's
Reflections pane reads from the same vault directory.

Design notes:
[ADR-002](./obsidian_vault/01_Architecture/ADR-002-Hermes-Memory-Agent.md),
[ADR-003](./obsidian_vault/01_Architecture/ADR-003-Hermes-Token-Memory-Model.md),
[ADR-005](./obsidian_vault/01_Architecture/ADR-005-Code-Graph-Integration.md).

---

## MCP integration

`trustlayer-mcp` is a Python FastMCP server that exposes the SDK +
guardian + Hermes as MCP tools so any MCP-aware agent can drive
TrustLayer without per-language bindings.

```bash
cd mcp-server
python -m venv .venv
.venv/bin/pip install -e ../sdks/python -e .

# Stdio (default — what Claude Code / IDE clients launch as a subprocess)
.venv/bin/trustlayer-mcp

# SSE (for remote agents over HTTP)
TRUSTLAYER_MCP_TRANSPORT=sse \
TRUSTLAYER_MCP_BIND=127.0.0.1:8090 \
.venv/bin/trustlayer-mcp
```

Five tools, each a pure handler that wraps an SDK call:

| MCP tool | Wraps |
|---|---|
| `trustlayer_emit_event` | `TrustLayerClient.emit` |
| `trustlayer_guardian_check` | `GuardianClient.check` |
| `trustlayer_hermes_ingest` | `HermesAgent.ingest[_jsonl]` |
| `trustlayer_hermes_get_session` | `HermesAgent.session_events` |
| `trustlayer_hermes_reflect` | `HermesAgent.reflect` |

Register the stdio server with Claude Code by adding it to
`.claude/settings.json`:

```jsonc
{
  "mcpServers": {
    "trustlayer": { "command": "trustlayer-mcp" }
  }
}
```

---

## The protocol

The wire format and HTTP API are a versioned, RFC-2119
specification — [`spec/v0.1/`](./spec/v0.1/). Six documents:

1. [Wire format](./spec/v0.1/01-wire-format.md) — `AgentTraceEvent`
   envelope, encoding rules, strict-envelope policy.
2. [Event types](./spec/v0.1/02-event-types.md) — payload contracts
   for the seven `event_type` values.
3. [Cynefin domain](./spec/v0.1/03-cynefin.md) — enum semantics and
   the `CHAOTIC` ESCALATE-by-default rule.
4. [Policy language](./spec/v0.1/04-policy-language.md) — CSL syntax,
   `MatchSpec`, dotted-path payload predicates.
5. [HTTP API](./spec/v0.1/05-http-api.md) — required + optional
   routes, auth, metrics, rate limit, OTel interop.
6. [Conformance](./spec/v0.1/06-conformance.md) — three claimable
   surfaces (wire format, policy engine, HTTP API) each with
   normative MUST clauses.

Conformance fixtures (deterministic JSON the reference implementations
must parse identically) live at
[`spec/v0.1/fixtures/`](./spec/v0.1/fixtures/). The Rust core's
cross-language test loads them on every push.

Versioning policy: [`docs/VERSIONING.md`](./docs/VERSIONING.md).
Implementation mirror (developer-friendly view of the same wire format):
[`docs/SCHEMA.md`](./docs/SCHEMA.md).

---

## Configuration reference

### Sidecar (`trustlayer-guardian`)

| Env var | Default | Purpose |
|---|---|---|
| `TRUSTLAYER_BIND` | `127.0.0.1:8089` | Listen address. |
| `TRUSTLAYER_POLICY` | `./policies/default.json` | Policy file. |
| `TRUSTLAYER_POLICY_RELOAD` | `true` | `false` disables the file watcher. |
| `TRUSTLAYER_EVENTS_PATH` | `./events.jsonl` | JSONL trace store. `""` = in-memory only. |
| `TRUSTLAYER_VAULT_PATH` | `./obsidian_vault` | Vault root for `/v1/reflections`. |
| `TRUSTLAYER_API_TOKEN` | _(unset)_ | When set, every route except `/healthz` and `/metrics` requires `Authorization: Bearer <token>`. |
| `TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC` | _(unset)_ | `POST /v1/events` rate limit per second. Unset / `0` = unlimited. |
| `RUST_LOG` | `info` | Tracing filter. |

### SDKs

| Env var | Used by | Purpose |
|---|---|---|
| `TRUSTLAYER_API_TOKEN` | Python, TypeScript, Go | Bearer token fallback when no `api_key` is passed explicitly. |

### Dashboard (Vite build-time env)

| Env var | Default | Purpose |
|---|---|---|
| `VITE_TRUSTLAYER_BASE_URL` | `http://127.0.0.1:8089` | Sidecar URL. |
| `VITE_TRUSTLAYER_API_TOKEN` | _(unset)_ | Bearer token; sent on every request when set. |

### MCP server

| Env var | Default | Purpose |
|---|---|---|
| `TRUSTLAYER_MCP_TRANSPORT` | `stdio` | `stdio` or `sse`. |
| `TRUSTLAYER_MCP_BIND` | `127.0.0.1:8090` | SSE bind address. |

---

## Repo layout

```
trustlayer/
├── core-rs/               Rust core + trustlayer-guardian sidecar
├── sdks/
│   ├── python/            trustlayer-sdk (+ trustlayer.otel)
│   ├── typescript/        @trustlayer/sdk
│   └── go/                trustlayer (Go SDK)
├── skills/
│   └── hermes/            Memory + reflection subagent
├── mcp-server/            FastMCP bridge to SDK + guardian + Hermes
├── dashboard/             React + Vite observability UI
├── spec/                  Citable, versioned protocol spec
│   └── v0.1/              Active spec + conformance fixtures
├── obsidian_vault/        ADRs, agent skills, memory, reflections
├── docs/                  ARCHITECTURE, SCHEMA, VERSIONING, CURRENT_STATUS
└── .github/workflows/     CI: rust × python × typescript × go
```

---

## Status & roadmap

297 tests across the matrix, all green in CI:

| Surface | Tests |
|---|---|
| Rust core (`core-rs`) | 86 (lib unit + cross-language + HTTP + policy-watch) |
| Python SDK (`sdks/python`) | 49 |
| Hermes (`skills/hermes`) | 44 |
| MCP server (`mcp-server`) | 21 |
| TypeScript SDK (`sdks/typescript`) | 33 |
| Dashboard (`dashboard`) | 33 |
| Go SDK (`sdks/go`) | 31 |
| **Total** | **297** |

**Shipped (Phases 1–6 Slice 4c):** SDKs in four languages, policy
engine with payload predicates and hot-reload, trace store with
filtered queries, append-only persistence, dashboard, MCP server
(stdio + SSE), Hermes memory + reflections + code graph, bearer-token
auth, ingest rate limit, Prometheus `/metrics`, OpenTelemetry bridge,
formal v0.1 spec with conformance fixtures, Apache-2.0 LICENSE,
CONTRIBUTING + CHANGELOG + SemVer policy, matrix CI.

**In progress (Phase 6 Slice 4 remainder):**

- `pyo3` FFI embedding of the Rust guardian into Python (drops the
  ~100µs HTTP cost on the hot path).
- LLM-backed reflector for Hermes (the `ReflectionEngine` Protocol
  seam is already in place).
- Distributed event store (single-host JSONL is fine until it isn't).

**Pre-`v0.1.0` release tasks:** tag releases per
[`docs/VERSIONING.md`](./docs/VERSIONING.md), publish to PyPI / npm
/ pkg.go.dev / crates.io, ship a `docker-compose.yml` quickstart,
publish the spec at a stable URL.

The authoritative roadmap and per-phase detail live in
[`docs/CURRENT_STATUS.md`](./docs/CURRENT_STATUS.md).

---

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the schema-change
protocol, ADR cadence, new-SDK checklist, per-layer commands, and
PR workflow.

- **Schema changes** must touch the Python, TypeScript, and Rust
  mirrors in one PR, plus a cross-language test.
- **Architectural decisions** get an ADR in
  `obsidian_vault/01_Architecture/` before the code.
- **Tests are the contract** for shipped behaviour — new behaviour
  ships with a new test.

---

## License

Apache License 2.0. See [`LICENSE`](./LICENSE).
