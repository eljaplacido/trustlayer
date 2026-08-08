//! Payload predicate evaluation, shared by the policy engine and the evidence
//! engine (ADR-008, extended by ADR-018).
//!
//! v0.1 shipped one predicate form: a dotted path whose resolved value must be
//! deep-equal to a JSON literal. That answers "is it exactly this?" and nothing
//! else, which is enough for a policy rule and not enough for an evidence
//! query — an auditor asks "which of these tools", "how long did it take",
//! "was it any of the restricted ones".
//!
//! This module adds comparison operators **without a second language**
//! (principle P6): controls and policies speak the same dialect, so a control
//! can reference the policy that enforces it and a gap can be remediated by
//! emitting a rule from the same predicate.
//!
//! ## Disambiguation
//!
//! Operators are `$`-prefixed. An expected value is an operator expression iff
//! it is an object whose keys all begin with `$`; anything else keeps its v0.1
//! deep-equality meaning, so every policy written before this module still
//! means exactly what it meant.
//!
//! A *mixed* object — some `$` keys, some not — is rejected by
//! [`validate_predicate`] rather than silently treated as a literal. A typo
//! like `{"$gt": 5, "unit": "ms"}` would otherwise become a deep-equality
//! comparison that can never match, and a rule that never fires is a rule
//! nobody notices is broken.
//!
//! ## No regular expressions, deliberately
//!
//! `$prefix` and `$suffix` cover what catalogs actually need (`restricted.*`
//! style tool families). A regex engine evaluated over a million events on
//! behalf of a user-supplied catalog is a denial-of-service primitive, and the
//! evidence engine is exactly where untrusted-ish input meets unbounded data.

use serde_json::Value;

/// Every supported operator key.
pub const OPERATORS: &[&str] = &[
    "$eq",
    "$ne",
    "$in",
    "$nin",
    "$gt",
    "$gte",
    "$lt",
    "$lte",
    "$exists",
    "$contains",
    "$prefix",
    "$suffix",
];

/// Is this expected-value an operator expression rather than a literal?
fn is_operator_object(expected: &Value) -> bool {
    match expected {
        Value::Object(map) => !map.is_empty() && map.keys().all(|k| k.starts_with('$')),
        _ => false,
    }
}

/// Reject predicates that would silently mean something other than intended.
///
/// Returns a human-readable reason, or `None` when the predicate is well
/// formed. Callers validate at parse time so evaluation stays infallible on
/// the hot path.
pub fn validate_predicate(path: &str, expected: &Value) -> Option<String> {
    let Value::Object(map) = expected else {
        return None; // any non-object literal is a valid deep-equality target
    };
    if map.is_empty() {
        return None;
    }

    let dollar: Vec<&String> = map.keys().filter(|k| k.starts_with('$')).collect();
    if dollar.is_empty() {
        return None; // a plain object literal; deep equality
    }
    if dollar.len() != map.len() {
        let plain: Vec<&str> = map
            .keys()
            .filter(|k| !k.starts_with('$'))
            .map(String::as_str)
            .collect();
        return Some(format!(
            "predicate for {path:?} mixes operators with literal keys ({plain:?}). \
             Either make every key an operator, or none — a mixed object would be \
             compared literally and could never match."
        ));
    }
    for key in dollar {
        if !OPERATORS.contains(&key.as_str()) {
            return Some(format!(
                "predicate for {path:?} uses unknown operator {key:?}. Known: {OPERATORS:?}"
            ));
        }
    }
    // Operand types. Caught here rather than at evaluation, where a wrong type
    // would just silently fail to match every event.
    for (key, operand) in map {
        let wrong_type = match key.as_str() {
            "$in" | "$nin" => !operand.is_array(),
            "$gt" | "$gte" | "$lt" | "$lte" => !operand.is_number(),
            "$exists" => !operand.is_boolean(),
            // `$contains` also accepts array membership, so any scalar operand
            // is meaningful there; `$prefix`/`$suffix` are string-only.
            "$prefix" | "$suffix" => !operand.is_string(),
            _ => false,
        };
        if wrong_type {
            return Some(format!(
                "predicate for {path:?}: operator {key} has an operand of the wrong type"
            ));
        }
    }
    None
}

/// Evaluate one predicate against a resolved value.
///
/// `actual` is `None` when the dotted path did not resolve. A missing path
/// fails every operator except `$exists: false` and `$ne` — asserting that an
/// absent field differs from a value is true, and is how a control expresses
/// "this must not be set to X".
pub fn matches_predicate(actual: Option<&Value>, expected: &Value) -> bool {
    if !is_operator_object(expected) {
        // v0.1 semantics, unchanged: deep equality, missing path never matches.
        return actual.is_some_and(|a| a == expected);
    }

    let Value::Object(ops) = expected else {
        return false;
    };

    // Every operator in the object must hold (implicit AND), matching how
    // MatchSpec already ANDs its fields.
    ops.iter().all(|(op, operand)| match op.as_str() {
        "$exists" => operand.as_bool() == Some(actual.is_some()),
        "$eq" => actual.is_some_and(|a| a == operand),
        "$ne" => actual.is_none_or(|a| a != operand),
        "$in" => actual.is_some_and(|a| {
            operand
                .as_array()
                .is_some_and(|items| items.iter().any(|i| i == a))
        }),
        "$nin" => actual.is_none_or(|a| {
            operand
                .as_array()
                .is_some_and(|items| !items.iter().any(|i| i == a))
        }),
        "$gt" => compare_numbers(actual, operand, |a, b| a > b),
        "$gte" => compare_numbers(actual, operand, |a, b| a >= b),
        "$lt" => compare_numbers(actual, operand, |a, b| a < b),
        "$lte" => compare_numbers(actual, operand, |a, b| a <= b),
        "$prefix" => match_strings(actual, operand, |a, b| a.starts_with(b)),
        "$suffix" => match_strings(actual, operand, |a, b| a.ends_with(b)),
        "$contains" => match actual {
            // A string contains a substring; an array contains an element.
            Some(Value::String(s)) => operand.as_str().is_some_and(|needle| s.contains(needle)),
            Some(Value::Array(items)) => items.iter().any(|i| i == operand),
            _ => false,
        },
        // Unknown operators are rejected at validation time; refusing to match
        // here means a predicate that slipped through cannot silently pass.
        _ => false,
    })
}

fn compare_numbers(actual: Option<&Value>, operand: &Value, cmp: fn(f64, f64) -> bool) -> bool {
    match (actual.and_then(Value::as_f64), operand.as_f64()) {
        (Some(a), Some(b)) => cmp(a, b),
        // A non-numeric value is not "less than" anything. Coercing strings
        // here would make `latency_ms: "12"` compare as a number in one
        // catalog and a string in another.
        _ => false,
    }
}

fn match_strings(actual: Option<&Value>, operand: &Value, cmp: fn(&str, &str) -> bool) -> bool {
    match (actual.and_then(Value::as_str), operand.as_str()) {
        (Some(a), Some(b)) => cmp(a, b),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn matches(actual: Value, expected: Value) -> bool {
        matches_predicate(Some(&actual), &expected)
    }

    fn missing(expected: Value) -> bool {
        matches_predicate(None, &expected)
    }

    // --- v0.1 deep equality is untouched ---------------------------------

    #[test]
    fn literals_still_use_deep_equality() {
        assert!(matches(json!("shell"), json!("shell")));
        assert!(!matches(json!("shell"), json!("bash")));
        assert!(matches(json!({"a": [1, 2]}), json!({"a": [1, 2]})));
        assert!(matches(json!(true), json!(true)));
    }

    #[test]
    fn a_missing_path_never_matches_a_literal() {
        assert!(!missing(json!("shell")));
        assert!(!missing(json!(null)));
    }

    #[test]
    fn an_object_literal_without_dollar_keys_is_still_a_literal() {
        // Guards the disambiguation rule: real payloads contain objects, and
        // they must keep comparing as values.
        assert!(matches(json!({"in": [1]}), json!({"in": [1]})));
        assert!(!matches(json!({"in": [2]}), json!({"in": [1]})));
    }

    #[test]
    fn an_empty_object_is_a_literal_not_an_operator() {
        assert!(matches(json!({}), json!({})));
        assert!(!matches(json!({"a": 1}), json!({})));
    }

    // --- operators --------------------------------------------------------

    #[test]
    fn eq_and_ne() {
        assert!(matches(json!("a"), json!({"$eq": "a"})));
        assert!(!matches(json!("a"), json!({"$eq": "b"})));
        assert!(matches(json!("a"), json!({"$ne": "b"})));
        assert!(!matches(json!("a"), json!({"$ne": "a"})));
    }

    #[test]
    fn ne_holds_for_a_missing_path() {
        // "must not be set to X" has to be true when the field is absent,
        // otherwise a control can never assert a negative.
        assert!(missing(json!({"$ne": "restricted"})));
    }

    #[test]
    fn in_and_nin() {
        assert!(matches(json!("b"), json!({"$in": ["a", "b"]})));
        assert!(!matches(json!("c"), json!({"$in": ["a", "b"]})));
        assert!(matches(json!("c"), json!({"$nin": ["a", "b"]})));
        assert!(!matches(json!("a"), json!({"$nin": ["a", "b"]})));
    }

    #[test]
    fn in_does_not_match_a_missing_path() {
        assert!(!missing(json!({"$in": ["a"]})));
    }

    #[test]
    fn numeric_comparisons() {
        assert!(matches(json!(10), json!({"$gt": 5})));
        assert!(!matches(json!(5), json!({"$gt": 5})));
        assert!(matches(json!(5), json!({"$gte": 5})));
        assert!(matches(json!(4.5), json!({"$lt": 5})));
        assert!(matches(json!(5), json!({"$lte": 5})));
    }

    #[test]
    fn numeric_comparison_does_not_coerce_strings() {
        // Coercing would make `latency_ms: "12"` behave differently between
        // two catalogs that both look correct.
        assert!(!matches(json!("12"), json!({"$gt": 5})));
        assert!(!matches(json!(true), json!({"$gt": 0})));
    }

    #[test]
    fn exists() {
        assert!(matches(json!(null), json!({"$exists": true})));
        assert!(!missing(json!({"$exists": true})));
        assert!(missing(json!({"$exists": false})));
        assert!(!matches(json!("x"), json!({"$exists": false})));
    }

    #[test]
    fn prefix_and_suffix() {
        assert!(matches(
            json!("restricted.delete"),
            json!({"$prefix": "restricted."})
        ));
        assert!(!matches(
            json!("safe.delete"),
            json!({"$prefix": "restricted."})
        ));
        assert!(matches(
            json!("payments.transfer"),
            json!({"$suffix": ".transfer"})
        ));
    }

    #[test]
    fn contains_works_for_strings_and_arrays() {
        assert!(matches(json!("hello world"), json!({"$contains": "lo wo"})));
        assert!(!matches(json!("hello"), json!({"$contains": "xyz"})));
        assert!(matches(json!(["a", "b"]), json!({"$contains": "b"})));
        assert!(!matches(json!(["a"]), json!({"$contains": "b"})));
    }

    #[test]
    fn multiple_operators_are_anded() {
        let range = json!({"$gte": 1, "$lte": 10});
        assert!(matches(json!(5), range.clone()));
        assert!(!matches(json!(11), range.clone()));
        assert!(!matches(json!(0), range));
    }

    #[test]
    fn an_unknown_operator_never_matches() {
        // Validation rejects these; refusing to match means one that slipped
        // through cannot silently pass a control.
        assert!(!matches(json!("x"), json!({"$nope": "x"})));
    }

    // --- validation -------------------------------------------------------

    #[test]
    fn well_formed_predicates_validate() {
        for expected in [
            json!("literal"),
            json!(42),
            json!({"nested": "literal"}),
            json!({"$in": ["a"]}),
            json!({"$gte": 1, "$lte": 10}),
            json!({"$exists": false}),
        ] {
            assert_eq!(validate_predicate("p", &expected), None, "{expected}");
        }
    }

    #[test]
    fn a_mixed_object_is_rejected() {
        let reason = validate_predicate("latency", &json!({"$gt": 5, "unit": "ms"}))
            .expect("must be rejected");
        assert!(reason.contains("mixes operators"), "{reason}");
    }

    #[test]
    fn an_unknown_operator_is_rejected() {
        let reason = validate_predicate("p", &json!({"$regex": "a.*"})).expect("must be rejected");
        assert!(reason.contains("unknown operator"), "{reason}");
    }

    #[test]
    fn operand_types_are_checked() {
        assert!(validate_predicate("p", &json!({"$in": "not-an-array"})).is_some());
        assert!(validate_predicate("p", &json!({"$gt": "not-a-number"})).is_some());
        assert!(validate_predicate("p", &json!({"$exists": "yes"})).is_some());
        assert!(validate_predicate("p", &json!({"$prefix": 5})).is_some());
    }
}
