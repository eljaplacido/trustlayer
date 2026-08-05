---
adr: 23
title: Agentic Workbench UIX
date: 2026-08-02
status: proposed
---

# ADR-023 — Agentic Workbench UIX

## Context

The dashboard is seven panes stacked on one scrolling page (`App.tsx`),
React 18 + Vite, **no router, no state library, no CSS framework**, styled
with inline `React.CSSProperties` objects that repeat the same hex codes
in every file. It reads; it never writes.

The goal is a workbench where an operator selects evidence, asks a model
about it, and receives a reviewable proposal — a document, a policy, a
code change — that a human accepts. Three constraints shape how far to go:

1. The current app is small and clean. A rewrite would trade a working
   read surface for months of risk.
2. Every runtime dependency added to a compliance product is a supply
   chain claim you have to defend. The current dependency list is `react`
   and `react-dom`. That is an asset.
3. A static Vite app cannot write to the user's repo. Something must hold
   the pen.

## Decision

### 1. The dashboard is the lens. The agentic client is the hand.

The **MCP server is the write path.** It already bridges the SDK,
Guardian, and Hermes to MCP-aware clients and gains proposal tools:
`trustlayer_list_proposals`, `trustlayer_get_proposal`,
`trustlayer_apply_proposal`.

The user reviews a proposal in the dashboard and applies it through
Claude Code or OpenCode — clients that already have file-write
permissions, diff review, and human approval built in, under the user's
own credentials.

This avoids standing up a write-capable web service with its own auth,
CSRF, and path-traversal surface inside a product whose entire value is
trustworthiness. It is also the more honestly *agentic* answer: the agent
does the work, the human approves it, and the dashboard is where you see
what happened. A localhost-only `trustlayer-workbench serve` for non-MCP
users is deferred to Phase 9 and is not needed for the workflow to close.

### 2. No new runtime dependencies

- **Routing:** a ~25-line `useHashRoute()` hook. The dashboard is
  internal and hash routing covers deep-linking to a session, a control,
  or a run. `react-router` is not justified by this need.
- **State:** `useReducer` per workbench surface. No Redux, no Zustand.
- **Charts:** if a chart is needed, inline SVG. No charting library.

Dev dependencies (testing-library, vitest) are already present and are
where the investment goes instead.

### 3. Design tokens first, components second

`dashboard/src/theme.ts` extracts colors, spacing, radii, and type scale
from the seven panes that currently repeat them. This is the precondition
for everything else: dark mode, contrast auditing, and consistent status
semantics all need one source of truth.

Accessibility is a requirement, not a polish pass:

- **Status is never encoded in colour alone.** Today's PASS/FAIL/GAP
  badges pair an icon with colour; the new `AssuranceBadge` and
  `EgressBadge` carry text too, and a test asserts the text is present.
  This matters for the compliance semantics specifically: a colour-blind
  auditor must not be able to misread `declared` as `verified`.
- Keyboard navigation through the proposal diff, with visible focus.
- `aria-live="polite"` on the evaluator console so findings are announced.
- WCAG AA contrast for every token pair, checked in a unit test over
  `theme.ts` rather than by eye.

### 4. Component set

| Component | Role |
|---|---|
| `EvidenceInspector` | evidence window selection; shows `seq` range and integrity status |
| `EvaluatorConsole` | scoped conversation with an evaluator role; renders findings **with their citations as links into the trace** |
| `ProposalDiff` | unified diff, rationale, cited evidence, apply-via-MCP instructions |
| `RunCard` | one `EvaluatorRun`: model, prompt version, cost, latency, ungrounded-rejected count, human decision |
| `AssuranceBadge` | declared / evidenced / verified — never a blended score |
| `EgressBadge` | local / EU / third-country, resolved against the system's data classes |
| `QueryBuilder` | NL → compiled `evidence_query`, shown for review before execution |

A finding whose citation cannot be resolved to a visible event renders as
an error, not as a finding. The UI is the last place the grounding
contract (ADR-020 §3) is enforced.

### 5. Natural language compiles to a query, never to an answer

The `QueryBuilder` sends natural language to the eval layer and receives
an **`evidence_query` JSON** validated against the ADR-018 v2 schema. The
compiled query is displayed for review, then executed deterministically by
the evidence engine.

The user sees the query and the events. They never see model prose
presented as a result. This keeps every answer reproducible, auditable,
and cheap to re-run — and it means a wrong answer is a visibly wrong
query rather than an invisible hallucination.

### 6. Progressive disclosure over a rewrite

The seven existing panes stay. A `#/workbench` route is added alongside
them; the Compliance pane gains links into it. Panes migrate to `theme.ts`
incrementally. At no point is the working read surface broken.

Phase 8 polls run records on an interval. Live token streaming is Phase 9
and needs the serve-mode decision resolved first — polling is honest,
simple, and sufficient for runs measured in seconds.

### 7. Skill alignment: one source of truth

Canonical agent skills live in `.opencode/skills/<name>/SKILL.md`.
`.claude/skills/<name>` becomes a **symlink** to the canonical directory,
so Claude Code and OpenCode read the same file and cannot drift. Git
tracks symlinks natively; duplicated skill files would diverge within
weeks.

New skills — `evidence`, `evaluators`, `workbench` — and each states its
**refusal conditions** explicitly, because a skill is how the next agent
session inherits this design:

- `evaluators`: never emit a finding without citations; never add a role
  without a grounded output model.
- `evidence`: never widen an assurance tier to make a scan pass.
- `workbench`: never add a runtime dependency without an ADR; never
  encode status in colour alone.
- `compliance` (extended): never present output as legal advice or
  certification; propose, never apply.

## Consequences

- Runtime dependencies stay at `react` + `react-dom` through Phase 8.
- The write path requires an MCP-aware client. Users without one can read
  everything and apply proposals manually from the displayed diff; this is
  documented rather than hidden, and Phase 9 revisits serve mode if the
  friction proves real.
- `theme.ts` touches all seven existing panes. Migration is incremental
  and each pane's existing tests must stay green — the panes are the
  regression suite for the refactor.
- The a11y assertions add real test surface. That is the intended cost:
  an accessibility bug in a compliance product is itself a compliance
  problem.
- Hash routing means no server-side routing config and no deploy change,
  at the cost of uglier URLs. Acceptable for an internal tool.
