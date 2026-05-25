# 4. Policy Language (CSL)

**Status:** Normative.

The Constraint Specification Language is the declarative DSL the
guardian consumes. A policy is a named, **ordered** list of rules.
Each rule has a [`MatchSpec`](#42-matchspec) selector and a
`Decision`. The guardian returns the **first** matching rule; if no
rule matches, a default verdict is produced (§4.5).

## 4.1 Policy document

A policy MUST be encoded as a JSON object of the following shape:

```json
{
  "name": "string",
  "rules": [
    { /* PolicyRule */ }
  ]
}
```

- `name` — REQUIRED. Identifies the policy; surfaced in the
  guardian verdict (§5.2) as `policy`.
- `rules` — REQUIRED. An ordered array of [`PolicyRule`](#42-policyrule)
  objects. An empty array is valid; the guardian then always returns
  the default verdict (§4.5).

The reference Rust implementation uses serde with `deny_unknown_fields`
on `Policy` and `PolicyRule`; implementations MAY do the same. The
contract here is the JSON; how it is validated internally is an
implementation choice.

## 4.2 `PolicyRule` and `MatchSpec`

```json
{
  "name":     "string",
  "match":    { /* MatchSpec */ },
  "decision": "PASS | FAIL | ESCALATE",
  "reason":   "string"
}
```

- `name` — REQUIRED. Surfaced in the verdict as `rule`.
- `match` — OPTIONAL. Defaults to the empty selector, which matches
  every event. (Used to author a catch-all rule.)
- `decision` — REQUIRED. MUST be one of `PASS`, `FAIL`, `ESCALATE`.
- `reason` — OPTIONAL. Carried verbatim into the verdict's `reason`
  when this rule fires.

### `MatchSpec`

`MatchSpec` fields are ANDed together. An unset field matches any
value. All fields are OPTIONAL; the empty `MatchSpec` matches every
event.

| Field | Type | Matches when… |
|---|---|---|
| `event_type` | `EventType` | the event's `event_type` equals this. |
| `tool_name` | `string` | the event's `payload.tool_name` equals this. Syntactic shortcut for `payload: { "tool_name": "..." }`. |
| `agent_id` | `string` | the event's `agent_id` equals this. |
| `cynefin_domain` | `CynefinDomain` | the event's `cynefin_domain` equals this. |
| `payload` | `map<dotted-path, json>` | every dotted path in the map resolves to a value deep-equal to its JSON literal. See §4.3. |

## 4.3 Payload predicates

The `payload` field of `MatchSpec` is an extension introduced in v0.1
(per ADR-008). Its semantics are normative:

- Keys are **dotted paths** into the event's top-level `payload`
  object. Implementations MUST split on `.` and walk segment-by-
  segment.
- Each value is an arbitrary JSON literal. Implementations MUST
  compare the resolved value to the literal using **deep equality**.
- Segments that look like non-negative integers (e.g. `"0"`,
  `"1"`, `"42"`) index JSON arrays. All other segments are object
  keys.
- If any segment fails to resolve — missing key, walking through a
  non-collection, out-of-range index — the predicate MUST NOT match.
- A `null` JSON literal matches `null` JSON **values** only.
  It MUST NOT match an absent key.
- Implementations MUST NOT perform type coercion: `1` MUST NOT match
  `1.0`; `"true"` MUST NOT match `true`.
- Predicates AND together. Every dotted-path / literal pair MUST
  match for the rule to fire.

### Examples (informative)

```json
{
  "match": {
    "event_type": "TOOL_CALL",
    "payload": {
      "model": "gpt-4",
      "args.temperature": 1.0,
      "args.tools.0": "shell"
    }
  }
}
```

Matches a `TOOL_CALL` whose payload has `model` exactly `"gpt-4"`,
whose `args.temperature` exactly `1.0` (not `1`), and whose
`args.tools` array contains `"shell"` at index `0`.

### Keys with literal dots (informative)

This version does not define an escape syntax for payload keys that
themselves contain a literal `.`. Authoring rules against such keys
is out of scope for v0.1.

## 4.4 Order

Rules MUST be evaluated in the order they appear in `rules`. The
**first** matching rule wins; subsequent rules MUST NOT be consulted
once a match has been found. Authors place specific rules before
general ones.

## 4.5 Default verdict

When no rule matches, the guardian MUST emit a default verdict:

- If `event.cynefin_domain` is `CHAOTIC`, the default `decision`
  MUST be `ESCALATE` and the verdict's `reason` MUST be a non-null
  string indicating the Cynefin default fired.
- Otherwise, the default `decision` MUST be `PASS` and the verdict's
  `rule` MUST be `null`.

In both cases, the verdict's `policy` field MUST be the policy's
`name`.

## 4.6 Encoding

A policy document MUST be encoded as UTF-8 JSON per RFC 8259.
Implementations MAY support additional source formats (YAML, etc.)
that parse to the same JSON shape, but JSON is the wire form.

## 4.7 Hot reload (informative)

Implementations MAY watch the policy source and atomically swap
policies at runtime without restarting (per ADR-009). Whether they do
so is an implementation choice and is not part of conformance.
