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

## 4.3.1 Comparison operators (extension, ADR-018)

Deep equality answers "is it exactly this?" and nothing else. That is
enough for many policy rules and not enough for an evidence query
(§5.12, ADR-018), which must express "any of these tools", "longer than
this", "not set to that". This section adds operators **to the same
language** so a control and the policy rule enforcing it cannot drift
apart.

Support is OPTIONAL for a v0.1 conforming implementation. An
implementation that does not support operators MUST reject a policy
containing one rather than treat it as a literal — silently comparing an
operator object by deep equality yields a rule that can never match, and
a rule that never fires is a rule nobody notices is broken.

**Disambiguation.** An expected value is an operator expression **iff**
it is a JSON object whose keys **all** begin with `$`. Every other value
keeps its §4.3 deep-equality meaning, so a policy written before this
section means exactly what it meant.

An object with *some* `$`-prefixed keys and some plain keys is
malformed. Implementations MUST reject it at load time.

| Operator | Operand | Matches when |
|---|---|---|
| `$eq` | any | the resolved value deep-equals the operand |
| `$ne` | any | the value differs, **or the path is absent** |
| `$in` | array | the value deep-equals some element |
| `$nin` | array | the value equals no element, or the path is absent |
| `$gt`, `$gte`, `$lt`, `$lte` | number | both sides are numbers and the comparison holds |
| `$exists` | boolean | the path resolved (`true`) or did not (`false`) |
| `$contains` | any | a string value contains the operand substring, or an array value contains the operand element |
| `$prefix`, `$suffix` | string | a string value starts/ends with the operand |

Normative details:

- Operators within one object AND together, matching how `MatchSpec`
  already ANDs its fields.
- An absent path fails every operator **except** `$exists: false` and
  `$ne`/`$nin`. Asserting that an absent field differs from a value is
  true, and is how a control expresses "this must not be set to X".
- `$exists: true` MUST match a path that resolves to JSON `null`. An
  absent key and a present `null` are different facts.
- Numeric operators MUST NOT coerce. A string `"12"` MUST NOT compare as
  a number, and a boolean MUST NOT compare as `0`/`1`. Coercion would
  make the same catalog mean different things in two implementations.
- Implementations MUST reject an operand of the wrong type at load time
  (`$in` without an array, `$gt` without a number, `$exists` without a
  boolean, `$prefix`/`$suffix` without a string).
- An unrecognised `$` operator MUST be rejected at load time and MUST NOT
  match at evaluation time.

**There is deliberately no regular-expression operator.** `$prefix` and
`$suffix` cover the tool-family patterns catalogs need. A regex engine
evaluated over a large event stream on behalf of a user-supplied catalog
is a denial-of-service primitive, and the evidence engine is precisely
where a catalog meets unbounded data.

### Example (informative)

```json
{
  "match": {
    "event_type": "TOOL_CALL",
    "payload": {
      "tool_name": { "$prefix": "payments." },
      "args.amount": { "$gt": 10000 },
      "args.dry_run": { "$ne": true }
    }
  }
}
```

Matches a payments tool call over 10 000 that is not a dry run —
including calls where `dry_run` is absent entirely.

### Conformance

`spec/v0.1/fixtures/predicate-cases.json` is a normative table of
evaluation and validation cases. An implementation claiming operator
support MUST pass it. The reference implementations run it from
`core-rs/tests/predicate_conformance.rs` and
`compliance/tests/test_predicates.py`.

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
