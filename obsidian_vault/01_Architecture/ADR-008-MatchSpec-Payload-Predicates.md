---
adr: 008
status: accepted
date: 2026-05-24
tags: [architecture, phase-6, policy, csl, guardian]
supersedes: []
extends: ["[[ADR-004-Cynepic-Guardian-Policy-Engine]]"]
---

# ADR-008 — MatchSpec payload predicates (dotted-path equality)

## Context

`MatchSpec` ([[ADR-004-Cynepic-Guardian-Policy-Engine]]) currently
selects events by four top-level fields:

- `event_type`
- `tool_name` (which already reaches *into* the payload — a one-off
  exception we added so the simplest rules could be written)
- `agent_id`
- `cynefin_domain`

That works for "block this tool" / "escalate on chaotic" / "scope to one
agent" — but it cannot express **"block tool calls whose `payload.model`
is `gpt-4`"** or **"escalate when the planner's `payload.args.temperature`
is `1.0`"**, both of which came out of the production-readiness audit as
real policy needs.

Without first-class payload predicates, every non-trivial policy turns
into Rust code in `guardian.rs`. That's the opposite of what the CSL is
for.

## Decision

`MatchSpec` gains a fifth, optional field:

```rust
pub payload: Option<BTreeMap<String, serde_json::Value>>,
```

In policy JSON it looks like:

```json
{
  "name": "block_gpt4_external",
  "match": {
    "event_type": "TOOL_CALL",
    "tool_name": "external_llm",
    "payload": {
      "model": "gpt-4",
      "args.temperature": 1.0
    }
  },
  "decision": "FAIL"
}
```

### Matching semantics

- Each map key is a **dotted path** into the event's `payload` object,
  resolved left-to-right by splitting on `.`. `"model"` matches
  `payload.model`; `"args.temperature"` matches
  `payload.args.temperature`; `"args.tools.0"` matches the first
  element of `payload.args.tools` (array indexing is supported via
  numeric segments).
- Each value is a `serde_json::Value` literal. The predicate is
  **deep equality** between the value at the resolved path and the
  literal — *exactly* what `serde_json::Value::PartialEq` does.
  This makes `"model": "gpt-4"` match the string, and
  `"args": {"temperature": 1.0}` match the whole object.
- Predicates AND together. All must match for the rule to fire, the
  same as every other field on `MatchSpec`.
- A path that resolves to nothing (missing key, walking through a
  non-object, indexing past the end of an array) **does not match**.
  There is no "absent equals null" coercion.
- `null` literals match `null` values *and* `null` literals only —
  not missing keys. If you want to match "key is absent" you don't
  use payload predicates (this stays a non-goal; the audit didn't
  ask for it).

### What we are *not* doing

- **No JSONPath, JMESPath, or CEL.** Dotted equality covers >90% of
  policy needs at <5% of the complexity. We can introduce a full
  expression language behind a feature flag later if we ever see
  pressure for it.
- **No operators (`>`, `<`, regex, `contains`).** Same reason. The
  audit's example was equality (`payload.model == "gpt-4"`).
- **No type coercion.** `1` does not match `1.0` and `"true"` does
  not match `true`. The policy author writes the literal they mean.
  Cross-language tests check this against the Python SDK's actual
  JSON output.
- **No escape syntax for keys that contain dots.** Top-level
  payload keys with literal dots in their names are vanishingly rare
  in trace payloads; if we hit one we can add a quoting rule, but
  shipping it now is YAGNI.

### tool_name compatibility

The existing `tool_name` field already reaches into
`payload.tool_name`. We **keep** it as syntactic sugar — every existing
policy continues to parse. Internally it could be lowered to a payload
predicate (`{"tool_name": "..."}`), but explicit lowering would change
the JSON shape on the wire, which we don't want. So `tool_name` stays
as a top-level shortcut and the new `payload` map handles everything
else.

## Implementation sketch

- `core-rs/src/policy.rs` — extend `MatchSpec` with the new optional
  field; add a `resolve_path(payload, path) -> Option<&Value>` helper.
- `core-rs/src/guardian.rs::matches_event` — after the existing four
  checks, walk `payload` and short-circuit on any non-match.
- Unit tests in `guardian.rs::tests`:
    - flat key match (string, number, bool, array, object)
    - nested key match via `a.b.c`
    - array index match via `a.0`
    - missing key → no match
    - walking through a non-object → no match
    - null vs absent distinction
    - rule with both `tool_name` and `payload` ANDs correctly
- Cross-language test (`tests/cross_language.rs`) — Python SDK emits
  a real event, Rust evaluates it against a payload-predicate rule.
- Default policy (`core-rs/policies/default.json`) — add one
  illustrative rule using `payload` so operators have a worked
  example.
- `docs/SCHEMA.md` — extend the "MatchSpec" section with the new
  field, the dotted-path syntax, and the worked example. This is a
  **wire-format MINOR** change per `docs/VERSIONING.md` (additive,
  optional field).
- `CHANGELOG.md` — entry under `[Unreleased]`.

## Consequences

- **+** Operators can write meaningful policies without recompiling
  the guardian. The CSL stays declarative.
- **+** Wire-format MINOR — existing policies and SDK versions keep
  working unchanged.
- **+** Predictable semantics: any unfamiliar reader can predict what
  a `MatchSpec` will match by reading 6 lines of "matching semantics"
  above. No expression-language documentation needed.
- **−** Dotted-equality is genuinely limited. Operators who need
  numeric comparisons or regex will work around it for now; this
  pressure is the signal we'd need before promoting CSL to a full
  expression language.
- **−** Slightly more work per evaluation — one BTreeMap walk per
  rule. Measured at <1µs on local benches; acceptable.

## Follow-ups
- Operators (`>=`, `regex`, `in`) behind a `csl-expressions` feature
  flag, only if real policies demand it.
- A `--explain` CLI on the guardian binary that shows *why* a given
  event matched (which predicate fired) — falls out naturally now
  that predicates are first-class data.
- Escape syntax for dot-containing keys, if we ever see one in the wild.
