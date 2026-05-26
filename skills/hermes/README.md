# Hermes — TrustLayer memory & reflection subagent

Hermes is a Python subagent that turns the TrustLayer trace stream
into a navigable Obsidian vault. It runs **offline by default** — no
LLM call required — and produces:

- One markdown note per `(agent_id, session_id)` under
  `<vault>/03_Memory_Traces/<agent>/<session>.md`, with YAML
  frontmatter and a chronological event timeline.
- A dated synthesis under `<vault>/05_Reflections/reflection-
  <date>.md` summarising tool frequency, policy failures, latency
  totals, and other structural metrics across sessions.
- Optionally, a code-graph view of your repo under
  `<vault>/06_Code_Graph/<language>/`, one note per file / class /
  function, with `[[wikilink]]` sections for Calls / Imports /
  Inherits / Contains.

The dashboard's Reflections pane reads from the same `05_Reflections/`
directory the CLI writes to.

- **Requires:** Python 3.11+
- **Hard dep:** `trustlayer-sdk` (the schema)
- **Design:** [ADR-002](../../obsidian_vault/01_Architecture/ADR-002-Hermes-Memory-Agent.md), [ADR-003](../../obsidian_vault/01_Architecture/ADR-003-Hermes-Token-Memory-Model.md), [ADR-005](../../obsidian_vault/01_Architecture/ADR-005-Code-Graph-Integration.md)

See the root [README](../../README.md) for the full architecture.

## Quickstart

```bash
# From the repo root:
pip install -e sdks/python

# Ingest a JSONL file of AgentTraceEvents and run a reflection pass:
PYTHONPATH=skills python -m hermes.cli \
    --vault obsidian_vault \
    ingest traces.jsonl --reflect
```

This writes per-session notes to
`obsidian_vault/03_Memory_Traces/` and a synthesis note to
`obsidian_vault/05_Reflections/`. Re-running the same command is
idempotent: events deduplicate on `trace_id`.

## CLI

### `ingest`

```bash
python -m hermes.cli \
    --vault <vault-root> \
    ingest <path-to-events.jsonl> \
    [--reflect]
```

Accepts JSONL where each line is an `AgentTraceEvent`, a dict the
SDK schema can validate, or a JSON-encoded version of either.
`--reflect` runs a reflection pass after ingest and writes a dated
synthesis note.

### `import-code-graph`

```bash
python -m hermes.cli \
    --vault <vault-root> \
    import-code-graph --gitnexus-root <path-to-.gitnexus>
```

Reads a [GitNexus](https://github.com/abhigyanpatwari/GitNexus) JSON
graph (`graph.json` or `nodes.json` + `edges.json`) and emits one
Obsidian note per code entity. Decoupled from GitNexus's internal
storage — upstream format changes can't break the importer.

See [ADR-005](../../obsidian_vault/01_Architecture/ADR-005-Code-Graph-Integration.md)
for the design and the PolyForm Noncommercial license caveat on
GitNexus itself.

## Library use

```python
from hermes.hermes_agent import HermesAgent
from trustlayer import AgentTraceEvent

agent = HermesAgent(vault_path="obsidian_vault")
agent.ingest(events)       # accepts AgentTraceEvent, dict, or JSON-string
agent.reflect()            # runs the default deterministic reflector
session = agent.session_events("researcher-1", "S1")
```

### Token / memory model (ADR-003)

`HermesAgent` is bounded by design so it doesn't blow up under a
firehose:

| Knob | Default | Effect |
|---|---|---|
| `max_payload_chars` | `2000` | Recursive truncation of large string fields with `<...truncated N chars>` marker. |
| `max_cached_sessions` | `256` | Bounded LRU cache. Markdown is flushed before eviction; reflection rehydrates from disk on demand. |
| `persist_events` | `True` | Append-only JSONL sidecar at `<vault>/.hermes_state/`. Crash-resumable. |
| `state_path` | `<vault>/.hermes_state/` | Override the sidecar location. |

For LLM-friendly summaries, each session exposes
`SessionSummary.compact_text(max_chars=600)` — a one-line, token-lean
form suitable for prompt context.

### Pluggable reflection (ADR-002)

The default reflector is `DeterministicReflector` — counts tools,
failed policies, latency totals, escalation rate. To swap in an
LLM-backed implementation, implement the `ReflectionEngine` Protocol:

```python
from hermes.reflector import ReflectionEngine, SessionSummary

class MyLLMReflector(ReflectionEngine):
    def reflect(self, summaries: list[SessionSummary]) -> str:
        # ...synthesise via your LLM of choice...
        return markdown

agent = HermesAgent(vault_path="obsidian_vault", reflector=MyLLMReflector())
```

The Protocol seam is in place; a first-party LLM reflector is on the
Slice 4 roadmap.

## Tests

```bash
cd skills/hermes
pip install -e ../../sdks/python   # SDK is the schema source
pytest                              # 44 cases
```

Coverage:

- `test_agent.py` — ingest idempotency, multi-format input coercion, multi-session separation.
- `test_reflector.py` — structural metric computation.
- `test_optimisation.py` — payload truncation, LRU eviction, JSONL persistence, compact-text formatting.
- `test_cli.py` — CLI exit codes + flag parsing.
- `test_code_graph.py` — GitNexus JSON parsing and note emission.
- `test_render.py` — markdown rendering.

## Vault layout

```
obsidian_vault/
├── 01_Architecture/        ADRs (written by hand)
├── 02_Agent_Skills/        Skill manifests (written by hand)
├── 03_Memory_Traces/       One note per session — Hermes writes these
│   └── <agent_id>/<session_id>.md
├── 05_Reflections/         One note per reflection pass — Hermes writes these
│   └── reflection-YYYY-MM-DD.md
├── 06_Code_Graph/          One note per code entity — Hermes writes these (optional)
│   └── <language>/<entity_id>.md
└── .hermes_state/          Internal sidecar JSONL (gitignored)
```

`01_Architecture/`, `02_Agent_Skills/`, etc. are authored by humans
and persist across Hermes runs. The directories Hermes writes are
fully derivable from the trace stream + state sidecar — deleting them
and re-running `ingest` produces the same content.

## Links

- [Root README](../../README.md) — full architecture, deployment, KPI playbook.
- [v0.1 specification](../../spec/v0.1/) — the wire format Hermes consumes.
- ADRs: [002 — Memory subagent](../../obsidian_vault/01_Architecture/ADR-002-Hermes-Memory-Agent.md), [003 — Token / memory model](../../obsidian_vault/01_Architecture/ADR-003-Hermes-Token-Memory-Model.md), [005 — Code-graph integration](../../obsidian_vault/01_Architecture/ADR-005-Code-Graph-Integration.md).
- [Contributing](../../CONTRIBUTING.md).
