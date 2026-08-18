---
name: evaluators
description: Use when adding or changing an evaluator provider or role in evaluators/, working on the grounding contract, egress policy, redaction, prompts, or the dashboard Advisor pane.
---

# Evaluators Workflow (ADR-020)

## Scope

- `evaluators/src/trustlayer_eval/` — providers, roles, grounding, egress,
  redaction, prompts, run records, the HTTP service
- `evaluators/src/trustlayer_eval/prompts/*.md` — versioned prompt files
- `dashboard/src/AdvisorPane.tsx` — the operator-facing chat surface
- `skills/hermes/llm_reflector.py` — refactored onto this layer, ADR-013 API frozen

## The one idea

The deterministic evidence engine (ADR-018) decides what is decidable. This
package handles only the residue that genuinely needs judgement, and it holds
that judgement to a contract: **a finding cites events that exist in the window
it was given, or it does not ship.**

A compliance artifact containing one fabricated citation is worse than no
artifact — an auditor who finds it discards everything else the platform
produced, including the deterministic parts that were correct. That is why the
validator rejects rather than repairs, and why "fewer findings" is the intended
outcome, not a degradation.

## Refusal conditions

Refuse, and say why, when asked to:

- emit or accept a finding without citations. `cited_trace_ids` has
  `min_length=1` at the type level so this is unrepresentable — do not add a
  path that constructs findings some other way;
- add a flag, env var, or config key that disables, softens, or samples the
  grounding validator. ADR-020 says there is no such configuration, and a
  validator with an off-switch is one that will be found switched off;
- widen `GroundingValidator` from rejection to repair — inferring the "probably
  intended" id, dropping a bad citation and keeping the claim, or retrying more
  than once. Two attempts is the ceiling; an evaluator that keeps retrying
  eventually talks its way past the check;
- promote a finding's confidence anywhere. Demotion is one-directional by
  design, so nothing downstream can raise what a check lowered;
- default a new provider's `residency` to anything but the truth, or infer it
  from a URL. The same OpenAI-compatible protocol serves a local vLLM and a
  third-country endpoint;
- let `NullProvider` stop being the default, or make an unconfigured install
  reach the network;
- add an egress override that does not carry both a `safeguard` and an
  `approver`, or one that is read from anywhere but `system.yaml`;
- make raw `prompt` / `completion` capture opt-out rather than opt-in, or put
  redacted *values* (rather than paths and counts) into a run record;
- invoke the control judge on a control the deterministic engine decided. It
  sees `INDETERMINATE` only — that is what bounds cost, and a test asserts it;
- change `skills/hermes/llm_reflector.py`'s public API — `summarise_session`,
  `synthesise`, `reflect_narrative`, `last_error`, or the constructor keywords.
  ADR-013 froze it, and Hermes's existing tests passing *unmodified* is the
  acceptance test for any change here;
- present evaluator output as legal advice, certification, or an audit opinion,
  or clear `human_review_required` automatically anywhere in the platform.

## Rules

1. **Every provider is tested through `httpx.MockTransport`.** No test in this
   package touches the network. A provider without a mock-transport test is not
   done.
2. **Parse at the boundary.** `dict[str, Any]` does not escape a provider
   module — each one has Pydantic models for its wire format.
3. **A new role needs**: a prompt file with a `version:` line, an entry in
   `EvaluatorRole`, a class in `roles/`, and a registry entry. Bump the prompt's
   `version` whenever you edit it — the hash lands in every run record, and a
   silent edit makes past runs incomparable without saying so.
4. **Adversarial fixtures are mandatory** for anything touching grounding:
   fabricated ids, ids from another window, duplicates, and empty citations.
   The positive cases pass under a broken validator too.
5. **Cost is bounded by construction, not by a budget check.** If you add a
   role that fans out, add the test that pins its call count.
6. **The run record is evidence.** Anything that changes what a run saw —
   window, prompt, provider, model, redaction — belongs in `EvaluatorRun`.
7. Telemetry failures are swallowed; the **policy check** is not. An
   unreachable guardian refuses the dispatch rather than defaulting to PASS —
   this is the one caller whose purpose is enforcing that distinction.
