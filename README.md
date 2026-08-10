# TrustLayer

**Open governance, observability, and trust for agentic AI.**

[![CI](https://github.com/eljaplacido/trustlayer/actions/workflows/ci.yml/badge.svg)](https://github.com/eljaplacido/trustlayer/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Wire format: v0.1](https://img.shields.io/badge/wire%20format-v0.1-informational)](./spec/v0.1/)
[![SDKs: Python · TypeScript · Go · Rust](https://img.shields.io/badge/SDKs-Python%20%C2%B7%20TypeScript%20%C2%B7%20Go%20%C2%B7%20Rust-6aa84f)](#integration-patterns)

TrustLayer is a self-hostable middleware and observability plane for
multi-agent systems. You instrument your agents through a small SDK
(Python, TypeScript, Go, or any HTTP client), point them at a Rust
sidecar, and get:

- a **policy engine** that adjudicates every tool call against a
  declarative ruleset (`PASS` / `FAIL` / `ESCALATE`),
- an **append-only trace store** that records every `AgentTraceEvent`,
- a **dashboard** with live Traces, Sessions, Reflections, Policy, and
  Compliance panes,
- a **memory subagent** that materialises sessions into a navigable
  Obsidian vault and runs recursive reflections,
- an **MCP server** that exposes the whole surface to any MCP-aware
  agent (Claude Code, MCP Inspector, frameworks),
- a **Prometheus `/metrics` endpoint** with verdict counts, latency
  histograms, and ingest volume,
- a **bridge to OpenTelemetry** (Python SDK today) that ships events into
  any existing OTel pipeline (OTLP, Jaeger, Tempo, Honeycomb, Grafana,
  Datadog).
- a **compliance toolkit** for machine-readable system registries, readiness
  checks, runtime evidence matching, dashboard reports, and audit packages.

No SaaS account. No telemetry leaking offsite. Apache-2.0. Four reference
SDKs and one wire format.

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
   - [Stack recipes](#stack-recipes)
6. [Policy engine](#policy-engine)
7. [Deployment](#deployment)
8. [Observability & KPIs](#observability--kpis)
9. [EU AI Act alignment](#eu-ai-act-alignment)
10. [Memory & reflections (Hermes)](#memory--reflections-hermes)
11. [MCP integration](#mcp-integration)
12. [The protocol](#the-protocol)
13. [Configuration reference](#configuration-reference)
14. [Developer tooling & agents](#developer-tooling--agents)
15. [Status & roadmap](#status--roadmap)
16. [Contributing](#contributing)
17. [Security](#security)
18. [License](#license)

**Start integrating:** [`docs/INTEGRATING.md`](./docs/INTEGRATING.md) — depth
levels (observe → guard → evidence → full plane) and stack recipes
(LangGraph, FastAPI, Next.js, Go workers, Claude Code / MCP, OTel).

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

**EU AI Act Article 50 readiness (from 2 Aug 2026).** Register systems,
configure nested disclosure/marking, emit `DISCLOSURE_SHOWN` /
`CONTENT_MARKED` events, run the readiness scanner in CI, and export an
audit package. Evidence support — not a legal certification.

**IDE / agent-native control plane.** Drive emit, guardian checks, and
Hermes via MCP from Claude Code, Cursor, or any MCP client without
per-language glue.

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
- `GET /v1/events/chained` — events with their Art. 12 chain position,
  cursor-paged (spec §5.12)
- `GET /v1/integrity/verify` — recompute the chain; a tampered log is
  `200` with `"ok": false`, because the request succeeded and its answer
  is that the log is broken
- `GET /v1/integrity/checkpoints` — signed commitments to chain heads

`/v1/integrity/verify` attests the chain **the running process holds**.
It does not re-read the store per request — that would turn an auditor's
request into a lever against the ingest path. So an edit made to
`events.jsonl` behind a live server is caught on the next cold read, not
by that server. To establish that a log was never edited, verify from a
restart (or read the store directly) and check the result against a
signed checkpoint obtained out of band. Spec §5.12.3 states this
normatively.
- `GET /metrics` — Prometheus exposition
- `GET /healthz` — liveness

The `/v1/integrity/*` routes are optional: a backend that keeps no chain
answers `501`, not `500`. It is healthy, it simply cannot attest — and a
`500` would read as a transient fault worth retrying.

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

Seven panes (see [`dashboard/README.md`](./dashboard/README.md)):

- **Overview** — KPI cards, event mix, registered agents
- **Metrics** — guardian Prometheus counters / histograms
- **Compliance** — readiness report from `public/compliance-readiness.json`
- **Traces** — live `AgentTraceEvent` stream (`GET /v1/events`)
- **Sessions** — one row per `(agent_id, session_id)`; click for timeline
- **Reflections** — Hermes synthesis notes
- **Policy** — recent `POLICY_CHECK` events with PASS / FAIL / ESCALATE

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
5. **Evidence** — `compliance/` maps registries + runtime events to
   control catalogues (EU AI Act, internal templates) and produces
   readiness / audit artefacts for the Compliance pane.

Full architecture: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).  
Stack integration guide: [`docs/INTEGRATING.md`](./docs/INTEGRATING.md).

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

### Stack recipes

| Your stack | How to integrate | Depth |
|---|---|---|
| **LangChain / LangGraph (Python)** | `@instrument_tool` on tools; `tracer.check` before model/tool nodes; use graph `thread_id` as `session_id` | Guard |
| **FastAPI / workers (Python)** | Per-request `Tracer`; gate outbound tools in service layer; scrape `/metrics`; optional `trustlayer.otel` | Guard + OTel |
| **Node / Next.js agents (TS)** | `wrapTool` + `tracer.check`; one `sessionId` per chat turn | Guard |
| **Go orchestrators** | `Tracer.Check` / `ToolCall` around shell, HTTP, and model clients | Guard |
| **Claude Code / Cursor / MCP IDEs** | Run `trustlayer-mcp` (stdio); call emit / guardian / Hermes tools | Full plane |
| **OTel shops (Tempo, Jaeger, Datadog)** | Keep your collector; add Python `OTelExporter` for span bridge | Observe |
| **Multi-language monorepo** | One guardian; Python + TS + Go SDKs; shared token; distinct `agent_id` | Guard |
| **Art. 50 transparency** | `system.yaml` + `DISCLOSURE_SHOWN` / `CONTENT_MARKED` + readiness scanner | Evidence |

Step-by-step copy-paste patterns: [`docs/INTEGRATING.md`](./docs/INTEGRATING.md).  
End-to-end demo (PASS/FAIL/ESCALATE + Hermes): [`examples/end_to_end_demo.py`](./examples/end_to_end_demo.py).

#### Article 50 disclosure / marking (all SDKs)

```python
from trustlayer import Tracer, EventType

tracer = Tracer(agent_id="chat-ui", session_id=session_id)
# After showing "You are interacting with an AI assistant"
tracer.emit(EventType.DISCLOSURE_SHOWN, {
    "surface": "chat_banner",
    "mechanism": "first_turn_notice",
})
# After labeling or watermarking generated content
tracer.emit(EventType.CONTENT_MARKED, {
    "content_type": "image",
    "method": "metadata",
})
```

Event types are available in Python, TypeScript, Go, and Rust
(`DISCLOSURE_SHOWN`, `CONTENT_MARKED`). Pair with a nested
`article_50` block in `system.yaml` (see
[`compliance/examples/system.yaml`](./compliance/examples/system.yaml)).

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

- `event_type` — one of the canonical `event_type` enum values
  (including `DISCLOSURE_SHOWN` and `CONTENT_MARKED`).
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

> **Secure by default:** the guardian refuses to bind a non-loopback
> address without `TRUSTLAYER_API_TOKEN`. Set a token, or (behind your own
> mTLS/proxy) opt out with `TRUSTLAYER_ALLOW_INSECURE=true`.

### Docker Compose

The repo ships a ready `Dockerfile` + `docker-compose.yml` (guardian +
dashboard, with an optional Hermes profile):

```bash
docker compose up            # guardian :8089, dashboard :5173
```

### Scaling: JSONL vs Postgres

Two trace-store backends sit behind one HTTP contract
([ADR-015](obsidian_vault/01_Architecture/ADR-015-Pluggable-Trace-Store-Postgres.md)) —
choose with env vars, not code:

| Backend | When | How |
|---|---|---|
| **JSONL** (default) | dev, demos, single node | nothing to configure; cap with `TRUSTLAYER_EVENT_RETENTION_MAX` |
| **Postgres** | production, HA, high volume | build `--features server,postgres`, set `TRUSTLAYER_DATABASE_URL` |

Run multiple stateless guardian replicas against one database:

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml \
  up --scale guardian=3
```

The Postgres schema is created automatically on connect. Full deployment,
retention, and security guidance: [`docs/SCALING.md`](docs/SCALING.md).

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

trustlayer_retention_live_events                          gauge
trustlayer_retention_archived_total                       gauge
trustlayer_retention_floor_blocked_total                  gauge
trustlayer_integrity_checkpoints_total                    gauge
trustlayer_integrity_chains_total                         gauge
```

The verdict and request counters are pre-touched at zero so
dashboards work from cold start.

The five gauges are the Art. 12 evidence surface, refreshed from the trace
store at scrape time. `trustlayer_retention_archived_total` counts events
moved to the archive log rather than deleted, and
`trustlayer_retention_floor_blocked_total` counts evictions the retention
floor refused. A backend that keeps no chain simply reports zero.

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
- **`trustlayer_retention_floor_blocked_total` rising** — the live log is
  outgrowing `TRUSTLAYER_EVENT_RETENTION_MAX` because the Art. 12 floor is
  correctly refusing to evict evidence that is still too young. Add disk or
  shorten the floor deliberately. It is never a reason to lower the floor
  reflexively, and it never means evidence was dropped.

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

## EU AI Act alignment

TrustLayer includes a compliance toolkit for **implementation and
evidence** workflows. It is an engineering control plane — **not** legal
advice, conformity assessment, or a certification.

Article 50 transparency duties depend on **role and use case**, not company
size, and the Digital Omnibus split their timeline:

| Obligation | Applies from | Binds |
|---|---|---|
| Art. 50(1) — disclose AI interaction | **live since 2026-08-02** | provider |
| Art. 50(3) — emotion recognition / biometric categorisation | **live since 2026-08-02** | **deployer** |
| Art. 50(4) — deepfake + public-interest text labelling | **live since 2026-08-02** | **deployer** |
| Art. 50(2) — machine-readable marking of synthetic content | **2026-12-02** (3-month grace for pre-Aug systems) | provider |

The split matters: 50(3) and 50(4) are *deployer* duties, routinely missed by
providers who assume the obligation stopped with them. TrustLayer encodes this
as data — `applies_to_roles` and `applies_from` in
`compliance/controls/article-50-v1.yaml` — so a deployer is never scored
against provider obligations and a control that has not commenced is reported
separately rather than as a gap to fix today.

High-risk (Annex III) obligations were deferred to **2027-12-02**. That does
not reduce the work: it means the evidence will be assessed against a *longer*
operating history, so runtime evidence captured now is worth more then than any
document produced late.

### What is included

| Component | Path | Role |
|---|---|---|
| System registry schema | `compliance/schemas/system.schema.json` | Ownership, risk class, oversight, nested `article_50` |
| Control catalogues | `compliance/controls/*.yaml` | EU AI Act, Aitomation template, Article 50 |
| Readiness scanner | `python -m compliance.src.readiness_scanner` | PASS/FAIL/GAP + score; CI exit codes |
| Evidence linker | `compliance/src/evidence_linker.py` | Match trace events to control `evidence_query` |
| Evidence query v2 | `compliance/src/evidence_query.py` | Coverage / sequence / absence / resolution predicates + assurance tiers |
| Remediation planner | `python -m compliance.src.remediation` | Ordered, cited plan across technical / documentation / process |
| Guidance catalog | `compliance/remediation/*.yaml` | How to close each gap — data, not code |
| Evidence integrity | `core-rs/src/integrity.rs`, `checkpoint.rs` | Art. 12 hash chain, retention floor, signed checkpoints |
| Report / audit generators | `report_generator.py`, `audit_generator.py` | Dashboard JSON + Markdown/JSON packages |
| Dashboard Compliance pane | `dashboard/src/CompliancePane.tsx` | Human-readable multi-system readiness |
| Hermes compliance graph | `skills/hermes/compliance_graph.py` | Obsidian notes under `07_Compliance/` |

### Quick compliance loop

```bash
# 1. Add system.yaml to your product repo (copy compliance/examples/system.yaml)
# 2. Instrument DISCLOSURE_SHOWN / CONTENT_MARKED where UX requires it
# 3. Scan
python -m compliance.src.readiness_scanner --project-dir /path/to/product \
    --output readiness.json

# 3b. Turn the gaps into work. Never writes to your project.
python -m compliance.src.remediation --readiness readiness.json \
    --output remediation.md --fail-on-blocking

# 4. Feed the dashboard (example fixture ships in dashboard/public/)
python -c "
from pathlib import Path
from compliance.src.report_generator import generate_dashboard_report
generate_dashboard_report([Path('/path/to/product')],
                          Path('dashboard/public/compliance-readiness.json'))
"

# 5. CI
./scripts/verify.sh compliance
```

### Article-level support mapping

| EU AI Act area | TrustLayer capability | Primary artifact |
|---|---|---|
| **Art. 9** Risk management | Policy-driven guardrails and recorded decisions | `POLICY_CHECK`, guardian policy files |
| **Art. 12** Logging / traceability | Append-only event stream + sessions | `/v1/events`, `/v1/sessions`, JSONL/Postgres |
| **Art. 13** Transparency | Structured traces, dashboard, system registry | Compliance pane + readiness report |
| **Art. 14** Human oversight | `ESCALATE` path and human-review hooks | `POLICY_CHECK` / `HUMAN_ESCALATION` |
| **Art. 15** Robustness monitoring | Latency, ingest, verdict metrics | `/metrics` + KPI tables above |
| **Art. 50** Transparency obligations | Nested disclosure/marking config; runtime events; scanner checks | `DISCLOSURE_SHOWN`, `CONTENT_MARKED`, Art. 50 controls, ADR-016 |

### Important boundary

Green readiness scores and linked traces help you **demonstrate** controls.
They do **not** replace legal interpretation, market-surveillance
cooperation, or organizational governance. Do not commit third-party
registries or private audit packages to this repo.

Strategy notes: [`docs/EU_AI_ACT_COMPLIANCE_STRATEGY.md`](./docs/EU_AI_ACT_COMPLIANCE_STRATEGY.md).  
Package docs: [`compliance/README.md`](./compliance/README.md).

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
   for canonical `event_type` values (including transparency events).
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
| `TRUSTLAYER_EVENT_RETENTION_MAX` | _(unset)_ | **Soft target** for live JSONL events. Overflow is *archived* to `events.archive.jsonl`, never deleted. Unset = unbounded. |
| `TRUSTLAYER_RETENTION_MIN_DAYS` | `180` | Art. 12 retention floor: minimum age before an event may leave the live log. **Outranks the target** — the log grows rather than destroy evidence. `730` for biometric / law-enforcement. `0` disables (dev only). |
| `TRUSTLAYER_SIGNING_KEY` | _(unset)_ | Ed25519 seed for chain checkpoints — a `chmod 600` file path, or hex. Prefer the file: an env var is readable from `/proc/<pid>/environ`. Unset ⇒ unsigned checkpoints, still emitted. |
| `TRUSTLAYER_INTEGRITY_CHECKPOINT_EVERY` | `1000` | Appends between chain checkpoints. `0` disables the count trigger. |
| `TRUSTLAYER_INTEGRITY_CHECKPOINT_INTERVAL_SECS` | `3600` | Seconds between checkpoints. `0` disables the time trigger. |
| `TRUSTLAYER_DATABASE_URL` | _(unset)_ | `postgres://…` DSN → use the Postgres backend (needs `--features server,postgres`). Empty = JSONL. |
| `TRUSTLAYER_DB_MAX_CONNECTIONS` | `10` | Postgres pool size per process. |
| `TRUSTLAYER_VAULT_PATH` | `./obsidian_vault` | Vault root for `/v1/reflections`. |
| `TRUSTLAYER_API_TOKEN` | _(unset)_ | When set, every route except `/healthz` and `/metrics` requires `Authorization: Bearer <token>`. |
| `TRUSTLAYER_ALLOW_INSECURE` | `false` | Allow binding a non-loopback address with no token. Off by default (the guardian refuses such binds). |
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
├── AGENTS.md              Agent / contributor operating contract
├── Makefile               verify / test / security / compliance targets
├── scripts/verify.sh      Canonical local release gate
├── core-rs/               Rust core + trustlayer-guardian sidecar
├── sdks/
│   ├── python/            trustlayer-sdk (+ trustlayer.otel)
│   ├── typescript/        @trustlayer/sdk
│   └── go/                trustlayer (Go SDK)
├── skills/hermes/         Memory + reflection + compliance graph
├── compliance/            Registries, scanners, evidence, remediation, audit
│   └── remediation/       Guidance catalogs (how to close each gap)
├── mcp-server/            FastMCP bridge to SDK + guardian + Hermes
├── dashboard/             React + Vite UI (7 panes incl. Compliance)
├── examples/              End-to-end demos
├── spec/v0.1/             Normative protocol + conformance fixtures
├── obsidian_vault/        ADRs, memory, reflections, 07_Compliance/
├── docs/                  ARCHITECTURE, INTEGRATING, SCHEMA, STATUS, …
├── .opencode/skills/      Scout / Plan / Build / Review / Compliance
└── .github/workflows/     CI matrix + compliance + security jobs
```

---

## Developer tooling & agents

| Tool | Purpose |
|---|---|
| `./scripts/verify.sh [test\|security\|compliance\|all]` | Local release gate (lint + types + tests + audits) |
| `make verify` / `make compliance` | Thin wrappers around `verify.sh` |
| [`AGENTS.md`](./AGENTS.md) | Required workflow for human and AI contributors |
| `.opencode/skills/{scout,plan,build,review,compliance}/` | Bounded agent skills for this monorepo |
| [`docs/INTEGRATING.md`](./docs/INTEGRATING.md) | Stack integration depth + recipes |
| [`docs/PROJECT.md`](./docs/PROJECT.md) | Mission, constraints, core commands |
| [`docs/CURRENT_STATE.md`](./docs/CURRENT_STATE.md) | Milestone, blockers, next action |

CI mirrors the gate: Python / TS / Go / Rust / Hermes / MCP / dashboard /
compliance / security (see `.github/workflows/ci.yml`).

---

## Status & roadmap

Local gate: `./scripts/verify.sh test` (see CI for the published matrix).

| Surface | Role |
|---|---|
| Rust core (`core-rs`) | Guardian, policy, trace store, metrics, HTTP API |
| Python / TypeScript / Go SDKs | Instrumentation + guardian clients |
| Hermes | Vault memory, reflections, compliance graph |
| Compliance | Registries, readiness, evidence, audit packages |
| MCP server | IDE / agent tool surface |
| Dashboard | Seven-pane operator UI |

**Shipped (Phases 1–7):** four SDKs, policy engine with payload predicates
and hot-reload, JSONL + Postgres trace stores, dashboard (Overview /
Metrics / Compliance / Traces / Sessions / Reflections / Policy), MCP
(stdio + SSE), Hermes (+ LLM reflector, code graph), bearer auth, rate
limit, Prometheus `/metrics`, OTel bridge (Python), formal v0.1 spec + fixtures,
Docker Compose, EU AI Act / Article 50 toolkit with nested config +
cross-SDK event parity (ADR-016), agent contract and verify gate.

**Shipped (Phase 8, in progress):**

- **Art. 12 evidence integrity** — per-`agent_id` hash chain, retention
  floor that outranks the count target, archive-on-overflow, Ed25519
  checkpoints, `GET /v1/integrity/*` (ADR-017, spec §5.12).
- **Assurance tiers** — `declared` / `evidenced` / `verified`, reported
  separately and **never blended into one score**. Coverage, sequence,
  absence and resolution predicates; role and commencement-date filtering
  (ADR-018).
- **Remediation guidance** — every gap comes with ordered, cited work
  across technical / documentation / process (ADR-024).
- **Agentic trust model, in part** — `HUMAN_DECISION`,
  `HARNESS_SNAPSHOT`, optional `parent_trace_id` (ADR-019). The event set
  is now eleven.

**Known deferrals**, stated rather than left to be found: Postgres
integrity parity (the backend answers `501`; run JSONL if you need scale
*and* Art. 12 integrity), streaming evidence evaluation, and the ADR-019
workflow graph.

**Next:** ADR-020 evaluators, ADR-021 Annex IV documents, ADR-022
incident pipeline, ADR-023 workbench UIX; package publish (PyPI / npm /
crates.io / pkg.go.dev); stable spec URL.

Detail: [`docs/CURRENT_STATUS.md`](./docs/CURRENT_STATUS.md) ·
[`docs/CURRENT_STATE.md`](./docs/CURRENT_STATE.md) ·
[`docs/RELEASE.md`](./docs/RELEASE.md).

---

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) and [`AGENTS.md`](./AGENTS.md).

- **Schema changes** must touch Python, TypeScript, Go, and Rust in one
  change set, plus cross-language tests / fixtures.
- **Architectural decisions** get an ADR under
  `obsidian_vault/01_Architecture/` and a row in `docs/DECISIONS.md`.
- **Tests are the contract** — new behaviour ships with a new test.
- Run `./scripts/verify.sh test` before claiming done.

Participation is governed by the
[Contributor Covenant](./CODE_OF_CONDUCT.md).

Good first contributions, if you are looking for one: a **new SDK** in a
language not yet covered (the wire format is specified precisely enough to
implement against, and `spec/v0.1/fixtures/` is a ready-made conformance
suite), a **default policy** for a regulated domain under `core-rs/policies/`,
or a **stack recipe** in [`docs/INTEGRATING.md`](./docs/INTEGRATING.md) for a
framework you already run.

---

## Security

Do not open a public issue for a suspected vulnerability. Use GitHub private
vulnerability reporting. [`docs/SECURITY.md`](./docs/SECURITY.md) covers the
reporting route, the deployment baseline (loopback by default, token required
off-loopback, TLS terminated upstream), and what not to put in a report.

---

## License

Apache License 2.0. See [`LICENSE`](./LICENSE).
