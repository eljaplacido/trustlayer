---
adr: 13
title: LLM-Backed Reflection for Hermes
date: 2026-05-30
status: accepted
---

# ADR-013 — LLM-Backed Reflection for Hermes

## Context

Hermes ships with a `DeterministicReflector` that produces structural
summaries (tool counts, policy failures, latency totals). The
`ReflectionEngine` Protocol was designed to accept an LLM-backed
implementation, but none existed. Operators and agent developers want
narrative reflections that identify anomalies, patterns, and risk
signals — something structural metrics alone cannot provide.

## Decision

Implement an `LLMReflector` class in `skills/hermes/llm_reflector.py` that:

1. Satisfies the `ReflectionEngine` Protocol.
2. Calls any Ollama-compatible (or OpenAI-compatible) chat endpoint with
   the structural summaries as input.
3. Fails gracefully: if the LLM is unreachable, times out, or returns an
   empty response, falls back to the deterministic path. Hermes never
   breaks because the LLM is unavailable.
4. Uses `SessionSummary.compact_text()` to build token-lean prompts so
   many sessions can fit in one LLM invocation.

The LLM is treated as an **optional enrichment**, not a hard dependency.
The structural reflection is always produced; the narrative is appended
to `Reflection.headline_metrics["narrative"]` when available.

### Prompt design

- System prompt: instructs the LLM to act as an observability operator,
  focus on anomalies and risk, and output plain text.
- User prompt: headline metrics + top tools + policy failures + per-session
  compact summaries.
- Temperature: 0.3 (low, for consistency).
- Default model: `nemotron-3-super:120b` (Ollama local), overridable.

### API surface

```python
from hermes.llm_reflector import LLMReflector

reflector = LLMReflector(
    endpoint="http://127.0.0.1:11434/api/chat",
    model="nemotron-3-super:120b",
    timeout=30.0,
)

# Protocol methods (same as DeterministicReflector)
summary = reflector.summarise_session(events)
reflection = reflector.synthesise([summary])

# Extended: full narrative + structured
result = reflector.reflect_narrative([summary])
# result.text       -> narrative string
# result.model      -> model used
# result.structured -> Reflection dataclass
```

### Backends supported

- **Ollama** (default) — `/api/chat` with `{"model": ..., "messages": [...], "stream": false}`.
- **OpenAI-compatible** — works with any endpoint that speaks the same
  chat-completions shape (LM Studio, vLLM, OpenRouter, Azure OpenAI).
- **Mock transport** — `httpx.MockTransport` for testing.

## Consequences

### Positive

- Operators get narrative reflections alongside structural metrics.
- The fail-safe design means Hermes works offline with zero LLM
  dependency.
- Token cost is controlled by `compact_text()` and low temperature.
- 12 new pytest cases verify LLM, HTTP error, empty response, and
  fallback paths.

### Negative

- Adds an `httpx` dependency to Hermes (already present via the SDK).
- LLM-resilience adds complexity to test surface.
- Narrative quality depends on the LLM; the prompt is tuned for
  instruction-following models.

## Alternatives considered

1. **OpenAI-only backend** — rejected. Ollama is the local-first
   default for gx10 and other self-hosted deployments.
2. **Build a custom agent loop** — rejected. The single-turn chat
   completions pattern is sufficient; multi-turn reflection can be
   added later.
3. **Make the LLM mandatory** — rejected. Breaks Hermes's "self-
   contained, zero config" design goal.
