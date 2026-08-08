---
adr: 19
title: Agentic Trust Model — Harness, Workflow, Envelope
date: 2026-08-02
status: partially-implemented
implemented: 2026-08-08
---

# ADR-019 — Agentic Trust Model: Harness, Workflow, Envelope

## Context

TrustLayer evaluates **events**. The trust properties of an agentic system
live one level up, in three objects the schema does not model:

- **The harness** — agent definitions, system prompts, tool manifests, MCP
  server configs, model bindings, memory scope, sandbox boundaries. This
  is Annex IV §2(a)–(c) (development methods, third-party tools, design
  specifications, architecture) and it is checkable without a single
  trace. Nothing fingerprints it, so nothing can detect when it changes —
  which is exactly what Art. 43 substantial modification and Annex IV §6
  lifecycle changes require (G7).
- **The workflow** — a session is a causal DAG, not a list. Delegation
  depth, sub-agent spawning, fan-out, retry storms, and the flow of data
  from low-trust tools into high-privilege ones are the agentic failure
  modes. None are representable today (G10).
- **The trust envelope** — the declared limits within which an agent is
  permitted to operate. Guardian enforces *per-call* policy; there is no
  session-scoped notion of "this run stayed inside its bounds". "No single
  call exceeded budget" is not "the session was safe".

A fourth, narrower gap: `CONTENT_MARKED` records that the system *claims*
to have marked content. For Art. 50(2) — applicable 2026-12-02 — evidence
that your code emitted a claim is materially weaker than evidence the
artifact carries a verifiable marking (G8).

And a structural hole in Art. 14: `HUMAN_ESCALATION` opens a loop that no
event closes. You can log that a human was asked; you cannot log what they
decided.

## Decision

### 1. Two new event types, one new optional envelope field

All three are MINOR per `spec/v0.1/01-wire-format.md` §1.7.

**`HUMAN_DECISION`** — closes the Art. 14 loop.

```json
{ "event_type": "HUMAN_DECISION",
  "payload": {
    "escalation_trace_id": "…",          // REQUIRED
    "decision": "APPROVE",               // REQUIRED: APPROVE | REJECT | MODIFY
    "reviewer_id": "…",                  // REQUIRED
    "rationale": "…",                    // RECOMMENDED
    "modified_args": { }                 // OPTIONAL, when decision == MODIFY
  },
  "metrics": { "latency_ms": 41200.0 } }
```

This is what makes ADR-018's `resolution` predicate expressible, and it
turns Art. 14 from a presence check into a measurable one: what fraction
of escalations were resolved, by whom, within what SLA.

**`HARNESS_SNAPSHOT`** — fingerprints the configuration a session ran
under. Emitted once per session, adjacent to `AGENT_START`.

```json
{ "event_type": "HARNESS_SNAPSHOT",
  "payload": {
    "harness_hash": "sha256:…",          // REQUIRED — hash of the normalised snapshot
    "model_bindings": [{"role": "planner", "model": "…", "provider": "…", "params_hash": "…"}],
    "tools":       [{"name": "…", "version": "…", "trust_tier": "privileged", "capabilities": ["net.egress"]}],
    "mcp_servers": [{"name": "…", "version": "…", "transport": "stdio"}],
    "prompt_hashes": {"system": "sha256:…", "planner": "sha256:…"},
    "autonomy":    {"max_delegation_depth": 3, "human_in_loop": true},
    "sdk":         {"name": "trustlayer-python", "version": "0.1.0"}
  } }
```

**Prompt *hashes*, not prompt text.** System prompts are trade secrets and
frequently contain customer data. The hash proves "this changed" without
disclosing what it says, which is the property Art. 43 detection actually
needs (P7).

**`parent_trace_id`** — a new OPTIONAL envelope field, the only envelope
change in Phase 8.

Unlike a chain hash (ADR-017 §1), causality is genuinely client-side
knowledge — only the agent knows which call spawned which. Inferring it
from ordering breaks under concurrency, which is precisely the regime
agentic systems operate in. The field mirrors OpenTelemetry's parent-child
relation, so ADR-012's exporter maps it directly. A spawned sub-agent's
`AGENT_START` carries the `trace_id` of the spawning `TOOL_CALL`, which is
what makes cross-agent delegation depth computable.

SDK emission is best-effort and absent by default; every derived metric
below degrades explicitly to `unknown` rather than guessing when the field
is missing.

### 2. The workflow graph is derived, never stored

`compliance/src/agentic/graph.py` builds a `WorkflowGraph` from a session's
events on demand. Nothing new is persisted; the graph is a projection.

Derived metrics, each with an explicit `unknown` when inputs are absent:

| Metric | Definition |
|---|---|
| `delegation_depth` | longest `parent_trace_id` chain crossing `AGENT_START` boundaries |
| `fan_out` | max children of any node |
| `retry_burst` | ≥N identical `TOOL_CALL`s within a window |
| `cycle_count` | cycles in the causal graph |
| `time_to_escalation` | first risky action → first `HUMAN_ESCALATION` |
| `human_decision_latency` | `HUMAN_ESCALATION` → `HUMAN_DECISION` |
| `unresolved_escalations` | escalations with no decision |
| `untrusted_to_privileged_flow` | see §3 |

### 3. Tool privilege lattice — and an honest label

Tools are classified in the harness snapshot and in a per-system tool
manifest: `trust_tier ∈ {untrusted, internal, privileged}` plus capability
tags (`net.egress`, `fs.write`, `payments`, `pii.read`).

The flow rule: a `TOOL_RESULT` from an `untrusted` tool, followed within
the same causal subtree by a `TOOL_CALL` to a `privileged` tool, is
flagged `untrusted-to-privileged-flow`. This is the agentic analogue of
taint tracking and it catches the dominant prompt-injection-to-action
pattern.

**It is a causal-proximity heuristic, not data-flow analysis.** We do not
track whether the untrusted bytes actually reached the privileged call's
arguments. It is reported as a `finding` requiring review, is never
rendered as a violation, and the word "heuristic" appears in the CLI
output, the dashboard, and the audit package. Overstating this would be
the fastest way to lose an auditor's trust in everything else the platform
says (P1, P10).

### 4. Trust envelope — post-hoc in Phase 8

Declared per system in `system.yaml`:

```yaml
trust_envelope:
  max_delegation_depth: 3
  max_autonomous_actions_without_human: 25
  session_cost_ceiling_usd: 5.00
  allowed_tool_graph:
    - {from: research.*, to: [summarise, store.write]}
  egress_allowlist: [api.internal.example]
  forbidden_capability_pairs: [[pii.read, net.egress]]
```

`compliance/src/agentic/envelope.py` evaluates completed sessions against
it and emits violations citing `trace_id`s, consumable as ADR-018
evidence.

**Runtime enforcement is explicitly Phase 9.** Guardian is per-call
stateless; envelope enforcement needs a bounded, TTL'd session accumulator
keyed by `(agent_id, session_id)`, which is a real change to its
concurrency and memory model and deserves its own ADR. Shipping post-hoc
first delivers the evidence value without destabilising the hot path
(P9).

### 5. Substantial-modification change records

`compliance/src/agentic/modification.py` diffs consecutive
`HARNESS_SNAPSHOT`s for an `agent_id` and produces a **Change Record**
feeding Annex IV §6 (ADR-021).

Classification is rule-based and configurable per system:

```yaml
substantial_modification_rules:
  substantial:
    - model_bindings[].model         # model family or version change
    - tools[].capabilities           # capability added
    - autonomy.human_in_loop         # oversight weakened
  non_substantial:
    - model_bindings[].params_hash   # temperature tweak
    - sdk.version
```

The store stays dumb: it does not emit derived events. Diffing is a
compliance-layer read over the trace store, consistent with ADR-015's
separation.

**"Substantial" is a legal determination.** The tool detects and
classifies changes and proposes a conclusion; a human decides under Art.
43. The change record carries a required `human_determination` field that
is `null` until set, and a change record with a null determination can
never satisfy a control above `DECLARED`.

### 6. Content marking verification

`CONTENT_MARKED` gains an OPTIONAL `verification` block:

```json
"verification": {
  "method": "c2pa",                    // c2pa | watermark | metadata | none
  "artifact_hash": "sha256:…",
  "verified": true,
  "verified_at": "…",
  "verifier": "trustlayer-marking-verify/0.1"
}
```

A pluggable `MarkingVerifier` protocol re-reads the artifact and confirms
the marking is present and well-formed. Only a verified marking can lift
an Art. 50(2) control to `VERIFIED` (ADR-018 §3); an unverified claim
stops at `EVIDENCED`. C2PA is the first concrete verifier; the protocol
keeps watermark schemes pluggable, since the Code of Practice on
AI-generated content is still settling.

## Consequences

- **Wire format:** two new event types, one new optional envelope field.
  All MINOR. Each ships with fixtures in `spec/v0.1/fixtures/` and
  round-trip tests in Python, TypeScript, Go, and Rust **in the same
  commit** (§5.3 of the Phase 8 design). Spec §2 gains the corresponding
  sections and the "seven" prose is corrected (ADR-018 §6).
- `parent_trace_id` is optional and unset by default. Existing traces stay
  valid; graph metrics report `unknown` rather than guessing. SDK helpers
  to populate it land per-SDK and are documented as opt-in.
- Prompt hashing means TrustLayer never stores prompt text from the
  harness snapshot — a deliberate limit on what an audit package can
  reveal, and one that makes the snapshot safe to share.
- The taint heuristic will produce false positives. Findings carry a
  suppression mechanism keyed by `(tool_pair, justification, approver)` so
  suppressions are themselves auditable evidence rather than silent
  config.
- Envelope evaluation is post-hoc, so a violation is detected after the
  fact. Documented plainly: Phase 8 gives you the evidence and the alarm,
  Phase 9 gives you the brake.

## Implementation status (2026-08-08)

**§1 shipped, in part.** The two event types landed across every layer in one
commit, under the lockstep discipline G0 taught: `core-rs` `EventType`, all
four SDKs, `control.schema.json`, spec §2.10/§2.11, `docs/SCHEMA.md`, two Go-
generated fixtures, and cross-language assertions. Spec §1.3, §2 and §6 now say
"eleven".

`HUMAN_DECISION` was not optional to defer. ADR-018 shipped a `resolution`
predicate that pairs `HUMAN_ESCALATION` with `HUMAN_DECISION`, and until this
commit no SDK could emit the second half — the predicate was expressible and
unusable. Closing that gap in the same phase it was opened is the point.

Two details worth recording:

- **`escalation_trace_id` is REQUIRED, not inferred.** Pairing by ordering
  looks adequate in a test and breaks under concurrency, which is the regime
  agentic systems operate in. Requiring the id makes the pairing wrong-or-
  absent rather than quietly wrong.
- **A cross-language test asserts the snapshot carries prompt *hashes*, not
  prompt text.** Fixtures are copied by integrators; one that leaked a system
  prompt would teach the wrong shape to everyone who read it. The test is
  cheap and the failure mode is not recoverable.

**Not yet built.** Stated here so it is not mistaken for done:

- **`parent_trace_id`** (§1). The only envelope change in Phase 8, and the one
  every derived metric in §2 depends on. Deferred because it touches the shipped
  v0.1 envelope in four SDKs, and it is worth landing on its own rather than
  behind two new event types.
- **The workflow graph** (§2) — `delegation_depth`, `fan_out`, `retry_burst`,
  `cycle_count`, `time_to_escalation`, `unresolved_escalations`. Without
  `parent_trace_id` most of these degrade to `unknown` anyway, so building them
  first would ship a module whose headline metrics are structurally
  unavailable.
- **The tool privilege lattice and untrusted-to-privileged flow detection**
  (§3). The `trust_tier` vocabulary is in the wire format and the fixture; the
  detector that consumes it is not written. When it is, §3's honesty
  requirement stands: it is a causal-proximity heuristic, reported as a finding
  for review, never as a violation, with the word "heuristic" in the CLI, the
  dashboard and the audit package.
- **The trust envelope** (§4) and substantial-modification change records.

Until the detector exists, a `HARNESS_SNAPSHOT` is evidence an operator can
diff by hand and nothing more. That is still worth emitting now: Art. 43
detection needs a *history* to compare against, and a history started in
2026 cannot be created retroactively in 2027.
