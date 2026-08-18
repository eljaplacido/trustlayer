---
adr: 20
title: trustlayer-eval — Pluggable Evaluator Providers with Grounded Output
date: 2026-08-02
status: accepted
accepted: 2026-08-16
---

# ADR-020 — `trustlayer-eval`: Pluggable Evaluator Providers with Grounded Output

## Context

The deterministic evidence engine (ADR-018) decides what is decidable.
A residue remains that genuinely needs judgement: is this risk register
adequate for the system's intended purpose; does this session show goal
drift; what would actually close this gap. Users want to point their own
model — local or cloud — at their traces and get diagnostics, documents,
and code back.

`skills/hermes/llm_reflector.py` (ADR-013) already establishes the correct
shape: Ollama by default, any OpenAI-compatible endpoint, `httpx` with a
`MockTransport` seam for tests, and **best-effort semantics with a
deterministic fallback** so the LLM is an enrichment and never a
dependency. It is however Hermes-private, single-purpose, and returns
free prose with no grounding contract (G11).

The risk to manage is specific and severe. A compliance artifact
containing one fabricated citation is worse than no artifact: an auditor
who finds it discards everything else the platform produced, including the
deterministic parts that were correct. Ungroundedness is not a quality
issue here, it is an existential one.

## Decision

### 1. A new top-level package, laid out like `compliance/`

`evaluators/` → Python package `trustlayer_eval`, with `src/`, `tests/`,
`pyproject.toml`, `requirements-release.txt`. It slots into
`scripts/verify.sh` as one more block (`ruff format --check`, `ruff
check`, `mypy`, `pytest`) and gets a `./scripts/verify.sh evaluators`
mode plus a CI job.

Hermes's `LLMReflector` is refactored onto it. **Its ADR-013 public API
does not change** — `summarise_session`, `synthesise`, `reflect_narrative`,
the constructor keywords — and its existing tests stay green unmodified.
That constraint is the acceptance test for the refactor.

### 2. Provider abstraction

```python
class ChatProvider(Protocol):
    name: str
    residency: Residency          # LOCAL | EU | THIRD_COUNTRY | UNKNOWN

    def complete(
        self, messages: Sequence[Message], *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> ProviderResponse: ...
```

Shipped implementations: `OllamaProvider` (default, `LOCAL`),
`OpenAICompatibleProvider` (vLLM, LM Studio, OpenRouter, Azure —
residency declared by config), `AnthropicProvider`, and `NullProvider`
(refuses every call; the default when nothing is configured, so a
misconfigured deployment degrades to deterministic-only rather than to
a surprise egress).

Provider responses are parsed into Pydantic v2 models **at the boundary**;
`dict[str, Any]` never escapes a provider module (§5.2 of the Phase 8
design). Every provider is tested through `httpx.MockTransport` — no test
touches the network.

Determinism: `temperature=0.0` and a seed where the backend supports it.
The prompt is hashed and recorded regardless, so a run is reproducible in
provenance even where the backend is not reproducible in output.

### 3. The grounding contract — the core of this ADR

Every evaluator returns a Pydantic model whose findings carry citations:

```python
class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str
    cited_trace_ids: tuple[UUID, ...] = Field(min_length=1)
    cited_sources: tuple[SourceRef, ...] = ()      # file:line, document anchors
    confidence: Confidence                          # LOW | MEDIUM | HIGH
    severity: Severity
    human_review_required: bool = True
```

`GroundingValidator` runs on every finding before it leaves the package:

1. Every `cited_trace_id` **must exist in the evidence window** that was
   supplied to the model. Ids outside the window, or invented, fail.
2. Every `cited_sources` path must resolve and the cited line range must
   exist.
3. Where a deterministic re-check exists for the claim's shape, it runs,
   and disagreement demotes confidence and flags the finding.

A failing finding is **rejected, not repaired**. One retry is issued with
the rejection reason appended; a second failure drops the finding and
increments `ungrounded_rejected` on the run record. The evaluator returns
fewer findings rather than unsupported ones. There is no configuration
that disables this.

This is P1 made mechanical. Adversarial test fixtures are mandatory for
this module: fabricated UUIDs, well-formed ids from a different session,
empty citation tuples, duplicated ids, and ids that exist but do not
support the claim.

### 4. Six evaluator roles

Each is a module with a shared `Evaluator` base, its own output model, and
its own prompt file under `evaluators/src/trustlayer_eval/prompts/`
(versioned and hashed, so a prompt change is visible in provenance).

| Role | Input | Output |
|---|---|---|
| `control_judge` | one `INDETERMINATE` control + its evidence window | verdict, gap reason, remediation |
| `workflow_critic` | a session's `WorkflowGraph` (ADR-019) | agentic failure-mode findings |
| `harness_auditor` | repo config: agent defs, tool manifests, MCP configs, prompts | static findings against Annex IV §2 |
| `document_author` | controls + evidence + system registry | Annex IV / Art. 13 / Art. 72 claims (ADR-021) |
| `code_emitter` | a gap + its control's predicate | CSL policy rule, SDK snippet, CI gate |
| `adversarial_verifier` | another role's finding | refutation verdict |

**Cost is bounded by construction.** The control judge is invoked *only*
on controls the deterministic engine marked `INDETERMINATE` (ADR-018 §3) —
never on ones it decided. A test asserts the model-call count for a
reference scan, so a regression that fans out across every control fails
CI rather than a customer's bill.

The `adversarial_verifier` runs on a **different provider or model** from
the one that produced the finding where two are configured. Same-model
self-verification is documented as weak and is reported as such in the run
record rather than silently counted as verification.

### 5. Egress policy and redaction

Traces carry prompts, responses, and potentially personal data. Sending a
system's traces to a third-country endpoint in order to assess its
compliance posture is self-defeating (P7).

`EgressPolicy` resolves from the system's `data_classes` × the provider's
declared `residency`:

- `personal_data` or `special_category_data` + `THIRD_COUNTRY` → the run
  is **refused**, with an error naming the data class, the provider, and
  the override mechanism.
- Override requires an explicit `egress_override` in `system.yaml`
  carrying a `safeguard` reference (adequacy decision, SCCs, DPA) and an
  approver. The override is recorded in the run and surfaces in the audit
  package — an auditable decision, not a config flag.
- `UNKNOWN` residency is treated as `THIRD_COUNTRY`.

`Redactor` runs before any egress. Default projection is the envelope plus
an allowlisted payload subset per system; raw `prompt`/`response` bodies
are **opt-in**, not opt-out. What was redacted is recorded (field paths
and a count, never values) so a reviewer can tell whether a finding was
made on partial information.

### 6. Dogfooding through Guardian

Every evaluator call emits `AgentTraceEvent`s through the Python SDK
(`AGENT_START`, `LLM_CALL`, `AGENT_END`) and is checked by
`GuardianClient.check()` before dispatch. A `FAIL` verdict refuses the
call.

TrustLayer's own model use is therefore traced, policy-gated, and
integrity-chained like any other agent — which also answers Annex IV §2(a)
("third-party tools used in development") for TrustLayer itself, from the
platform's own evidence store (P8).

### 7. The run record

```python
class EvaluatorRun(BaseModel):
    run_id: UUID
    role: EvaluatorRole
    provider: str
    model: str
    model_version: str | None
    prompt_hash: str
    evidence_window: EvidenceWindowRef   # query + result hash + seq range
    started_at: datetime
    duration_ms: float
    tokens_prompt: int
    tokens_completion: int
    cost_usd: float | None
    findings: tuple[Finding, ...]
    ungrounded_rejected: int
    redactions: RedactionSummary
    egress: EgressDecision
    human_decision: HumanDecisionRef | None
```

Persisted as JSONL under `compliance/runs/` and surfaced as run cards in
the workbench (ADR-023). The run record is itself Art. 12 evidence about
the tooling, and `evidence_window` pinning the query *and* a hash of its
result is what makes a past finding re-checkable against a log that has
since grown.

## Consequences

- New dependencies: `httpx` and `pydantic` (both already in the Python
  tree). No provider SDK is vendored — every backend is spoken to over its
  HTTP API, which keeps `requirements-release.txt` and the `pip-audit`
  surface small.
- `NullProvider` as the default means an unconfigured install produces
  deterministic results only, and never an unexpected network call. Opting
  in is a deliberate act.
- Findings will sometimes be *missing* rather than wrong, because the
  grounding validator drops what it cannot support. This is the intended
  trade and is stated in the UI: "N findings suppressed as ungrounded".
- Prompts are versioned files with hashes recorded in runs, so a prompt
  edit invalidates comparability between runs. The workbench marks runs
  from different prompt versions as not directly comparable.
- The refusal conditions are encoded in the `evaluators` agent skill: an
  agent working in this repo may not add an evaluator role without a
  grounded output model, and may not emit a finding without citations.
- **Limits stated in-product:** a grounded finding is a finding whose
  citations exist and support its shape. It is not a guarantee the
  judgement is correct. Every finding carries
  `human_review_required=True` by default and nothing in the platform
  clears that flag automatically.

## Implementation note — 2026-08-16

Shipped as Slice 8.4. The decisions above are unchanged; this section records
what implementation settled that the proposal left open.

**A seventh role.** `insight_advisor` was added alongside the six in §4 — the
operator-facing chat the dashboard's Advisor pane calls. It carries the same
grounding contract: it answers from cited events or says it cannot. It is
listed here rather than folded silently into §4 because the ADR named six.

**Two providers the proposal did not.** `AgentcenterProvider` routes through the
local agentcenter gateway so evaluator calls land in its KPI store alongside
every other local workload. It is the only provider with a fallback — to a
direct `OllamaProvider` when the gateway is down — and that is narrow on
purpose: both are local runtimes on the same machine, so the fallback cannot
change a run's residency. No other provider falls back to anything, because
silently substituting a different backend would make the run record's
`provider` field a lie.

**Guardian unreachability is a refusal, not a pass.** §6 says a `FAIL` verdict
refuses the call. It did not say what an *unreachable* guardian does. The SDK's
`GuardianClient` defaults to `fail_open=True`, which is right for instrumented
agents — telemetry must never take down a host. It is wrong here: this is the
one caller whose purpose is enforcing that distinction, so the evaluator layer
constructs its client with `fail_open=False` and refuses to dispatch an
unchecked call. Emission failures are still swallowed.

**Source citations with no repository root are demoted, not accepted.** §3
rule 2 requires cited paths to resolve. When no root is supplied there is
nothing to resolve them against; accepting them at face value would let an
unconfigured caller publish source citations nothing ever verified, so
confidence drops to `LOW` instead.

**Anthropic's sampling parameters are dropped, not forwarded.** `temperature`,
`top_p`, and `top_k` were removed from the current Claude models and now return
400. The `ChatProvider` protocol carries a `temperature` because local backends
need one, so `AnthropicProvider` drops it rather than forwarding it into a
rejected request. A safety refusal (HTTP 200 with `stop_reason: "refusal"`) is
raised as a provider error rather than read as an empty answer.
