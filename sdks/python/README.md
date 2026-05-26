# trustlayer-sdk (Python)

Python SDK for the TrustLayer protocol — emit
[`AgentTraceEvent`](../../spec/v0.1/01-wire-format.md)s, gate tool
calls with the [`cynepic-guardian`](../../core-rs/), and bridge into
any OpenTelemetry pipeline. Apache-2.0.

- **Wire-format conformance:** [v0.1 W1–W7](../../spec/v0.1/06-conformance.md)
- **Requires:** Python 3.11+
- **Hard deps:** `pydantic>=2`, `httpx>=0.25`
- **Optional extra:** `[otel]` → `opentelemetry-api`, `opentelemetry-sdk`

See the root [README](../../README.md) for the full architecture and
the [`spec/v0.1/`](../../spec/v0.1/) directory for the citable protocol.

## Install

```bash
# From the repo (editable):
cd sdks/python && pip install -e .

# With the OTel bridge:
pip install -e .[otel]

# With dev tooling (pytest, mypy, ruff, OTel):
pip install -e .[dev]
```

When `trustlayer-sdk` is on PyPI (pre-1.0 release pending), the
end-user install will be `pip install trustlayer-sdk` or
`pip install trustlayer-sdk[otel]`.

## Quickstart

### Instrument a tool call (context manager)

```python
from trustlayer import Tracer

tracer = Tracer(agent_id="researcher-1", session_id="S1")

with tracer.tool_call("web.search", {"q": "trustlayer"}) as out:
    out["value"] = run_search("trustlayer")
```

Emits a `TOOL_CALL` on entry and a `TOOL_RESULT` on exit (with
`metrics.latency_ms`). On exception the `TOOL_RESULT` carries the
exception repr in `payload.error` and the exception is re-raised
unchanged.

### Decorate a function once

```python
from trustlayer import Tracer, instrument_tool

tracer = Tracer(agent_id="researcher-1")

@instrument_tool(tracer, tool_name="web.search")
def search(query: str) -> list[str]:
    return run_search(query)

search("trustlayer")   # automatically emits TOOL_CALL + TOOL_RESULT
```

### Gate before invoking (guardian-aware)

```python
from trustlayer import Tracer, GuardianClient

tracer   = Tracer(agent_id="researcher-1", session_id="S1")
guardian = GuardianClient(policy_name="default")

verdict = tracer.check(
    "external_llm",
    {"prompt": "summarise report", "model": "gpt-4"},
    guardian=guardian,
)

if verdict["decision"] == "PASS":
    result = call_external_llm(...)
elif verdict["decision"] == "FAIL":
    raise PermissionError(verdict["reason"])
else:  # ESCALATE
    notify_oncall(verdict)
```

`Tracer.check()` emits the candidate `TOOL_CALL`, asks the guardian,
and emits a `POLICY_CHECK` carrying the verdict — both events share
a `trace_id` so the trace stream correlates the action with the
decision.

## Public API

### `TrustLayerClient`

Synchronous HTTP client that POSTs `AgentTraceEvent`s to a TrustLayer
ingest endpoint. Failures are logged at WARNING and **swallowed** —
instrumentation must never take down the host agent.

```python
from trustlayer import TrustLayerClient

client = TrustLayerClient(
    endpoint="http://127.0.0.1:8089/v1/events",  # default
    api_key=None,                                # falls back to env
    timeout=5.0,
)
client.emit(event)
client.emit_batch([e1, e2])
client.close()                # or use as `with TrustLayerClient(...)`
```

### `GuardianClient`

Synchronous client for `POST /v1/check`. **Fail-open by default**:
if the guardian is unreachable, returns a synthetic
`policy="fallback"` verdict whose `decision` is `PASS`. Pass
`fail_open=False` for hard denial.

```python
from trustlayer import GuardianClient

guardian = GuardianClient(
    endpoint="http://127.0.0.1:8089/v1/check",   # default
    policy_name="default",
    api_key=None,                                # falls back to env
    timeout=1.0,
    fail_open=True,
)
verdict = guardian.check(event, policy_name=None)
# verdict: TypedDict {decision, rule, reason, policy}
```

### `Tracer`

Bind an `(agent_id, session_id)` and emit typed events through a
shared `TrustLayerClient`.

```python
Tracer(
    agent_id: str,
    session_id: str | None = None,           # uuid4 if omitted
    client: TrustLayerClient | None = None,  # default constructor if omitted
    cynefin_domain: CynefinDomain = DISORDER,
)
```

Methods: `.emit(...)`, `.tool_call(...)`, `.policy_check(...)`,
`.check(...)`.

### `instrument_tool`

Function-decorator wrapper around `Tracer.tool_call`. The decorated
callable continues to work normally; events fire as a side effect.

### `trustlayer.otel.OTelExporter` (extra)

Drop-in replacement for `TrustLayerClient.emit` / `emit_batch` that
maps each event to one OTel span through the caller's
`TracerProvider`:

```python
from opentelemetry import trace as otel_trace
from trustlayer.otel import OTelExporter

# User wires up a TracerProvider + their exporter of choice
# (OTLP, Jaeger, Console, ...) as usual.
exporter = OTelExporter(tracer=otel_trace.get_tracer("my-agent"))
exporter.emit(event)
exporter.emit_batch([e1, e2])
```

Attribute naming (`trustlayer.*` prefix) is documented in
[spec §5.11](../../spec/v0.1/05-http-api.md#511-opentelemetry-interop-informative)
and [ADR-012](../../obsidian_vault/01_Architecture/ADR-012-OpenTelemetry-Exporter.md).
A runnable demo is at
[`examples/otel_exporter_demo.py`](./examples/otel_exporter_demo.py).

## Configuration

| Env var | Effect |
|---|---|
| `TRUSTLAYER_API_TOKEN` | Fallback bearer token for `TrustLayerClient` and `GuardianClient` when no `api_key` is passed. |

The bearer-token resolution order is:

1. Explicit `api_key=` keyword argument (always wins).
2. `TRUSTLAYER_API_TOKEN` env var.
3. None → no `Authorization` header is sent.

This matches the [ADR-007](../../obsidian_vault/01_Architecture/ADR-007-Auth-Bearer-Token.md)
sidecar gate: when the sidecar is configured with a token, every SDK
on every host picks it up by setting the same env var.

## Tests

```bash
pytest                          # 49 cases (33 core + 16 OTel)
```

Run from `sdks/python/`. The `[dev]` extra installs `pytest`, plus
the OTel SDK that the bridge tests exercise.

## Examples

- [`examples/langchain_style_agent.py`](./examples/langchain_style_agent.py) — minimal agent loop instrumented with the SDK.
- [`examples/otel_exporter_demo.py`](./examples/otel_exporter_demo.py) — wires a `TracerProvider` + `ConsoleSpanExporter` so every emitted event prints as an OTel span on stdout.

## Links

- [Root README](../../README.md) — full architecture, deployment, KPI playbook.
- [v0.1 specification](../../spec/v0.1/) — the citable protocol.
- [Conformance checklist](../../spec/v0.1/06-conformance.md) — what this SDK satisfies (W1–W7).
- [Versioning policy](../../docs/VERSIONING.md).
- [Contributing](../../CONTRIBUTING.md).
