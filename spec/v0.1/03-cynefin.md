# 3. Cynefin Domain

**Status:** Normative.

The `cynefin_domain` field classifies the *interaction context* of the
event. It exists so that policies can react differently to "novel /
unstable" interactions than to "well-understood / repeatable" ones.
The TrustLayer protocol borrows the framework's vocabulary; it does
not require that any specific Cynefin methodology be followed.

## 3.1 Enum

```
CynefinDomain := CLEAR | COMPLICATED | COMPLEX | CHAOTIC | DISORDER
```

Values MUST be encoded in `SCREAMING_SNAKE_CASE` (§1.3).

| Value | Semantics |
|---|---|
| `CLEAR` | The cause-and-effect relationship is obvious. Best-practice playbooks apply. |
| `COMPLICATED` | Cause-and-effect requires expertise but is knowable. Good-practice analysis applies. |
| `COMPLEX` | Cause-and-effect can only be understood in retrospect. Probe-sense-respond. |
| `CHAOTIC` | No clear cause-and-effect. Act first, then sense. |
| `DISORDER` | The domain has not been classified, or the emitter chooses not to assert one. |

## 3.2 Default

`DISORDER` is the default per §1.3. Emitters that cannot or do not
want to classify the interaction MUST either omit the field or set it
to `DISORDER`.

## 3.3 Use in policy evaluation

The `CynefinDomain` enum is consumed in two places by the reference
guardian (§4):

1. **As an explicit `MatchSpec` predicate** — a rule MAY match only
   when the event carries a specific domain.
2. **As the default verdict on `CHAOTIC`** — when no rule matches and
   the event's `cynefin_domain` is `CHAOTIC`, the guardian's default
   verdict MUST be `ESCALATE` rather than `PASS`. See
   [§4.5](./04-policy-language.md#45-default-verdict).

The first behaviour is configured per-policy; the second is a fixed
rule of the protocol.

## 3.4 Future values (informative)

The framework has been extended in the literature with additional
states. Adding a new value to this enum is a wire-format **MINOR**
change (§1.7). Receivers that do not recognize a value MUST treat
the envelope as valid (analogous to the rule for unknown
`event_type` values in §2.8).
