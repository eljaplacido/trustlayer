# trustlayer-eval

Point your own model at your traces and ask about them.

The deterministic evidence engine decides what is decidable. This package
handles the residue that genuinely needs judgement — *is this session drifting
from its goal, what would actually close this gap* — and holds that judgement
to one rule:

> **A finding cites events that exist in the window it was given, or it does not
> ship.**

Findings that fail that check are rejected, not repaired. The evaluator returns
fewer findings rather than unsupported ones. There is no configuration that
turns this off.

See [ADR-020](../obsidian_vault/01_Architecture/ADR-020-Trustlayer-Eval-Provider-Layer.md).

## Why so strict

A compliance artifact containing one fabricated citation is worse than no
artifact. An auditor who finds it discards everything else the platform
produced — including the deterministic parts that were correct. Ungroundedness
here is not a quality issue, it is an existential one.

## Quick start

```bash
pip install -e ../sdks/python -e .[dev,service]

# Nothing is called until you say so. The default provider refuses every
# request, so an unconfigured install never makes a surprise network call.
export TRUSTLAYER_EVAL_PROVIDER=ollama
export TRUSTLAYER_EVAL_MODEL=nemotron-3-nano:30b-a3b-q4_K_M

# Point at the trace store, and let the guardian police the evaluator's own
# model calls.
export TRUSTLAYER_BASE_URL=http://127.0.0.1:8089
export TRUSTLAYER_API_TOKEN=...          # if the sidecar has auth on
export TRUSTLAYER_ENABLED=true

# Where run records land. Resolved to an absolute path and reported by
# /health — the default follows the working directory, which is how one
# deployment ends up with run logs in three places.
export TRUSTLAYER_EVAL_RUNS_DIR=$PWD/../compliance/runs

trustlayer-eval-serve                     # 127.0.0.1:8091
```

Then open the dashboard's **Advisor** pane, or:

```bash
curl -s localhost:8091/v1/advisor/chat \
  -H 'content-type: application/json' \
  -d '{"question": "Which policy rules fired, and why?", "limit": 100}' | jq
```

## Providers

| `TRUSTLAYER_EVAL_PROVIDER` | Residency | Notes |
|---|---|---|
| `null` *(default)* | local | Refuses every call. Deterministic results are unaffected. |
| `ollama` | local | `TRUSTLAYER_EVAL_BASE_URL` defaults to `http://127.0.0.1:11434`. |
| `agentcenter` | local | Routes through the local gateway so runs land in its KPI store. Falls back to `ollama` when unreachable, and says so in the UI. |
| `openai_compat` | **declared** | vLLM, LM Studio, OpenRouter, Azure. Requires `TRUSTLAYER_EVAL_BASE_URL`; set `TRUSTLAYER_EVAL_RESIDENCY`. |
| `anthropic` | third country | Needs `ANTHROPIC_API_KEY`. |

Residency is **declared, never inferred**. The same OpenAI-compatible protocol
serves a vLLM process on your own machine and a model in another jurisdiction —
the URL cannot tell us which, so unset means `UNKNOWN`, and the egress policy
treats `UNKNOWN` as third-country.

## Egress

`data_classes` from `system.yaml` × the provider's residency:

- `personal_data` or `special_category_data` bound for a third country → the run
  is **refused**, naming the data class, the provider, and the override.
- Overriding requires an `egress_override` carrying a `safeguard` reference
  (adequacy decision, SCCs, DPA) **and** an `approver`. It is recorded in the run
  and surfaces in the audit package — an auditable decision, not a config flag.
  A half-filled override is not an override.

Redaction runs before any egress. The default projection is the envelope plus an
allowlisted payload subset; raw `prompt` / `completion` bodies are opt-in. What
was redacted is recorded as field paths and a count — never values — so a
reviewer can tell whether a finding was made on partial information.

## What a finding is, and is not

Every finding carries `human_review_required=True`, and nothing in the platform
clears it automatically.

A **grounded** finding is one whose citations exist and support its shape. That
is not a guarantee the judgement is correct. The validator can tell you a model
did not invent its evidence; it cannot tell you the model reasoned well about
it.

Findings will sometimes be *missing* rather than wrong — the validator drops
what it cannot support. The count is reported (`ungrounded_rejected`) and shown
in the UI as "N findings suppressed as ungrounded" rather than hidden.

## Self-governed

Every evaluator call emits `AgentTraceEvent`s through the Python SDK and is
policy-checked by the guardian before dispatch. TrustLayer's own model use is
traced, policy-gated, and integrity-chained like any other agent — which also
answers Annex IV §2(a) for TrustLayer itself, out of the platform's own
evidence store.

One deliberate asymmetry: telemetry failures are logged and swallowed, matching
every other SDK bridge, but a guardian that cannot be *reached* refuses the
dispatch rather than defaulting to PASS. This is the one caller whose entire
purpose is enforcing that distinction.

## Development

```bash
./scripts/verify.sh evaluators   # tests only
./scripts/verify.sh test         # the full gate
```

Every provider is exercised through `httpx.MockTransport`; no test in this
package touches the network. Grounding has adversarial fixtures — fabricated
ids, ids from another window, duplicates, empty citations — because the positive
cases pass under a broken validator too.
