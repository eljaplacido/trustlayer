---
date: 2026-05-07
phase: 2
status: complete
tags: [development, milestone, sdk]
links:
  - "[[../01_Architecture/ADR-001-SDK-Wedge]]"
  - "[[../../docs/CURRENT_STATUS]]"
---

# Phase 2 SDKs Shipped

## What landed
- **Python SDK** (`sdks/python/`): `schema.py` (Pydantic v2), `client.py`
  (httpx), `tracer.py` (context-managed `tool_call`, `policy_check`),
  `instrumentation.py` (`@instrument_tool` decorator). 15 pytest cases pass.
- **TypeScript SDK** (`sdks/typescript/`): `schema.ts` (Zod), `client.ts`
  (fetch with abort timeout), `tracer.ts`, `instrumentation.ts`
  (`wrapTool`). 16 vitest cases pass; `tsc --noEmit` clean under
  `strict + noUncheckedIndexedAccess`.
- Runnable examples in both SDKs that emit live events through a mock
  transport.
- Repo `.gitignore` covering Python, Node, Rust, editor, and OS artifacts.

## Why these choices
See [[../01_Architecture/ADR-001-SDK-Wedge]] for the full rationale. Key
points: schema mirrored across languages, injected transports for tests,
emit failures are non-fatal.

## Next up (Phase 3)
- `skills/hermes/hermes_agent.py` should consume `AgentTraceEvent` JSON,
  group by `session_id`, and write Markdown notes into
  `obsidian_vault/03_Memory_Traces/`.
- A second pass adds reflection — summarising N traces into a concept
  note that links back to its constituents.
