# Integrating TrustLayer With Your Stack

This guide is for application and platform engineers who want to put
TrustLayer on the hot path of tool-using agents without rewriting their
framework of choice.

**Contract:** the wire format is `AgentTraceEvent` ([`spec/v0.1/`](../spec/v0.1/)).
SDKs never take down the host agent on emit failure. The guardian is
fail-open by default.

## Choose an integration depth

| Depth | What you get | Effort |
|---|---|---|
| **A. Observe only** | Append-only traces + dashboard + metrics | Emit events (or use MCP tools) |
| **B. Guard tools** | A + `PASS` / `FAIL` / `ESCALATE` before each tool | Call `Tracer.check` / Guardian |
| **C. Govern + evidence** | B + system registry, readiness, Art. 50 events, audit package | Add `system.yaml` + compliance CLI |
| **D. Full plane** | C + Hermes vault + MCP for IDE agents | Run Hermes + `trustlayer-mcp` |

Most teams start at **A** or **B** in one service, then add **C** when legal
or security asks for Article 50 / high-risk evidence.

## Minimal path (any stack)

1. Run the sidecar: `cargo run --release --features server --bin trustlayer-guardian` in `core-rs/`.
2. Set `TRUSTLAYER_API_TOKEN` in production; leave unset only on loopback.
3. From your agent process, either:
   - use a first-party SDK (Python / TypeScript / Go), or
   - `POST /v1/events` and `POST /v1/check` with JSON (see root README raw HTTP).
4. Open the dashboard (`dashboard/`, default `http://127.0.0.1:5173`) pointed at the sidecar.

## Stack recipes

### Python — LangChain / LangGraph style

Wrap tools at the boundary you already control (tool registry or graph node):

```python
from trustlayer import Tracer, GuardianClient, instrument_tool

tracer = Tracer(agent_id="support-bot", session_id=thread_id)
guardian = GuardianClient(policy_name="default")

@instrument_tool(tracer, tool_name="crm.lookup")
def crm_lookup(customer_id: str) -> dict:
    return crm.get(customer_id)

def guarded_llm(prompt: str) -> str:
    verdict = tracer.check(
        "external_llm",
        {"prompt": prompt, "model": "gpt-4o-mini"},
        guardian=guardian,
    )
    if verdict["decision"] != "PASS":
        raise PermissionError(verdict["reason"])
    return call_model(prompt)
```

Point LangGraph nodes at `guarded_llm` / instrumented tools. Session id =
LangGraph `thread_id` (or equivalent) so the Sessions pane matches your runs.

Runnable sketch: [`sdks/python/examples/langchain_style_agent.py`](../sdks/python/examples/langchain_style_agent.py).

### Python — FastAPI / worker service

- Create one `Tracer` per request (or per job) with a stable `session_id`.
- Gate outbound tools in service methods, not in the HTTP layer only.
- Scrape guardian `/metrics` from Prometheus; optional OTel:

```python
from trustlayer.otel import OTelExporter
# after your TracerProvider is configured
otel = OTelExporter(tracer=otel_trace.get_tracer("my-service"))
```

### TypeScript — Node agent / Next.js route handlers

```ts
import { Tracer, GuardianClient, wrapTool } from "@trustlayer/sdk";

const tracer = new Tracer({ agentId: "web-agent", sessionId: reqId });
const guardian = new GuardianClient({ policyName: "default" });

const search = wrapTool(tracer, "web.search", (q: string) => runSearch(q));

const verdict = await tracer.check(
  "external_llm",
  { prompt, model: "gpt-4o-mini" },
  { guardian },
);
if (verdict.decision !== "PASS") throw new Error(verdict.reason);
```

Use the same `sessionId` across a chat turn so the dashboard timeline is one row.

### Go — orchestrators and sidecars

```go
client, _ := trustlayer.NewClient(trustlayer.ClientOptions{})
defer client.Close()
g, _ := trustlayer.NewGuardian(trustlayer.GuardianOptions{PolicyName: "default"})
tr := trustlayer.NewTracer(client, "orchestrator", sessionID)

verdict, _ := tr.Check(ctx, "shell", map[string]any{"cmd": cmd},
    &trustlayer.TracerCheck{Guardian: g})
```

### Claude Code / Cursor / MCP-aware IDEs

Run `trustlayer-mcp` (stdio) and register it as an MCP server. Tools:

| Tool | Use |
|---|---|
| `trustlayer_emit_event` | Log a structured event from the agent |
| `trustlayer_guardian_check` | Ask policy before a risky tool |
| `trustlayer_hermes_ingest` | Write sessions into the vault |
| `trustlayer_hermes_get_session` | Read back a session |
| `trustlayer_hermes_reflect` | Run reflection |

See [`mcp-server/README.md`](../mcp-server/README.md).

### OpenTelemetry-first shops

Keep your existing collector. Add `trustlayer.otel.OTelExporter` (Python)
so each `AgentTraceEvent` becomes a span with `trustlayer.*` attributes.
Guardian `/metrics` remains the policy KPI source; OTel is the distributed
trace plane.

### Multi-language monorepos

One guardian, many agents:

- Python research agent → Python SDK  
- TS UI agent → TypeScript SDK  
- Go workflow worker → Go SDK  

Same `TRUSTLAYER_API_TOKEN`, different `agent_id`, shared `session_id` when
they collaborate on one user task.

## Article 50 (transparency) instrumentation

When a human-facing disclosure or content mark happens, emit:

| Event | When |
|---|---|
| `DISCLOSURE_SHOWN` | User is told they interact with AI (banner, badge, voice prompt) |
| `CONTENT_MARKED` | Generated media/text is labeled or gets machine-readable provenance |

Register the system in `system.yaml` with nested:

```yaml
article_50:
  enabled: true
  disclosure_config:
    disclose_ai_interaction: true
    disclosure_mechanism: "UI banner on first chat turn"
  marking_config:
    mark_generated_content: true
    marking_method: "C2PA / metadata on export"
```

Then:

```bash
python -m compliance.src.readiness_scanner --project-dir .
# optional dashboard feed
python -c "from pathlib import Path; from compliance.src.report_generator import generate_dashboard_report; \
generate_dashboard_report([Path('.')], Path('dashboard/public/compliance-readiness.json'))"
```

Details: [`compliance/README.md`](../compliance/README.md), ADR-016.

## Policy as code in CI

```bash
# Local full gate
./scripts/verify.sh test

# Compliance-only
./scripts/verify.sh compliance
# or: make compliance
```

Gate releases on readiness scanner exit code and guardian policy unit tests
in `core-rs/`.

## What not to do

- Do not put secrets in event payloads.
- Do not claim legal compliance from a green readiness score alone.
- Do not bind the guardian off-loopback without `TRUSTLAYER_API_TOKEN`.
- Do not commit third-party `system.yaml` registries or live customer traces.

## Next documents

- Root [README](../README.md) — architecture, env vars, KPIs  
- [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md)  
- [`docs/SECURITY.md`](./SECURITY.md)  
- [`docs/SCALING.md`](./SCALING.md)  
- [`AGENTS.md`](../AGENTS.md) — agent/contributor operating contract  
