# TrustLayer

Open governance, observability, and trust layer for agentic AI.

TrustLayer instruments multi-agent systems, evaluates policies, and
turns the resulting trace stream into a navigable memory graph in an
Obsidian vault. One schema, two SDKs, a self-hostable memory subagent —
no SaaS dependency required.

## Status

| Phase | Component | State |
|---|---|---|
| 1 | Monorepo + schema + agent directives | shipped |
| 2 | Python + TypeScript SDKs (`AgentTraceEvent`, Tracer, instrumentation) | shipped |
| 3 | Hermes memory agent (Obsidian vault writer + reflector) | shipped |
| 3.5 | Hermes token/memory optimisation | shipped |
| 4 | Rust core: CSL policy parser + cynepic-guardian + HTTP gateway | shipped |
| 4.6 | Hermes code-graph importer (GitNexus JSON → Obsidian notes) | shipped |
| 5 | Dashboard + MCP server | planned |

See [`docs/CURRENT_STATUS.md`](./docs/CURRENT_STATUS.md) for the
authoritative roadmap and [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)
for the layered design.

## Quickstart

### Instrument an agent (Python)

```bash
cd sdks/python && pip install -e .
```

```python
from trustlayer import Tracer, PolicyCheckResult

tracer = Tracer(agent_id="researcher-1")

with tracer.tool_call("web.search", {"q": "trustlayer"}) as out:
    out["value"] = run_search("trustlayer")

tracer.policy_check(
    "pii_redaction",
    action="send_to_llm",
    result=PolicyCheckResult.PASS,
)
```

### Instrument an agent (TypeScript)

```bash
cd sdks/typescript && npm install && npm run build
```

```ts
import { Tracer } from "@trustlayer/sdk";

const tracer = new Tracer({ agentId: "researcher-1" });

const answer = await tracer.toolCall(
  "web.search",
  { q: "trustlayer" },
  () => runSearch("trustlayer"),
);

await tracer.policyCheck("pii_redaction", "send_to_llm", "PASS");
```

### Gate tool calls with the cynepic-guardian

```bash
# Build & launch the guardian (defaults to 127.0.0.1:8089)
cd core-rs
cargo run --release --features server --bin trustlayer-guardian
```

```python
from trustlayer import AgentTraceEvent, EventType, GuardianClient

with GuardianClient(policy_name="default") as g:
    verdict = g.check(AgentTraceEvent(
        agent_id="a", session_id="s",
        event_type=EventType.TOOL_CALL,
        payload={"tool_name": "external_llm"},
    ))
    # verdict["decision"] in {"PASS", "FAIL", "ESCALATE"}
```

Policies live in `core-rs/policies/*.json`. See
[`core-rs/README.md`](./core-rs/README.md).

### Materialise traces into an Obsidian vault (Hermes)

```bash
PYTHONPATH=skills python -m hermes.cli \
    --vault obsidian_vault \
    ingest traces.jsonl --reflect
```

This writes one note per `(agent_id, session_id)` to
`obsidian_vault/03_Memory_Traces/` and a dated synthesis to
`obsidian_vault/05_Reflections/`.

### Mirror a code graph into the vault (Hermes)

```bash
# Once GitNexus has produced .gitnexus/graph.json:
PYTHONPATH=skills python -m hermes.cli \
    --vault obsidian_vault \
    import-code-graph --gitnexus-root .gitnexus
```

Each code entity (file, class, function) becomes one note under
`obsidian_vault/06_Code_Graph/<language>/`, with `[[wikilink]]`
sections for Calls / Imports / Inherits / Contains. See
[`obsidian_vault/01_Architecture/ADR-005-Code-Graph-Integration.md`](./obsidian_vault/01_Architecture/ADR-005-Code-Graph-Integration.md).

## Repo layout

```
trustlayer/
├── core-rs/                 Rust core (Phase 4)
├── sdks/
│   ├── python/              trustlayer-sdk
│   └── typescript/          @trustlayer/sdk
├── skills/
│   └── hermes/              memory subagent (CLI + library)
├── obsidian_vault/          ADRs, agent skills, memory, reflections
└── docs/                    SCHEMA, ARCHITECTURE, CURRENT_STATUS
```

## License
Apache 2.0
