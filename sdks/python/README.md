# trustlayer-sdk (Python)

Lightweight Python SDK for emitting agent trace events to a TrustLayer collector.

## Install

```bash
pip install -e .[dev]
```

## Quickstart

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

The wire format is defined in `docs/SCHEMA.md` at the repo root and mirrored in
`sdks/typescript/src/schema.ts`.

## Test

```bash
pytest
```
