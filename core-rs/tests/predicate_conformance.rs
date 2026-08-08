//! Runs the shared predicate conformance table (spec §4.3, ADR-018).
//!
//! The same file drives `compliance/tests/test_predicates.py`. A predicate
//! language implemented twice and tested twice is a language that will
//! diverge, and divergence between the policy engine and the evidence engine
//! means a control can claim to be enforced by a rule that does not match the
//! same events. That is the G0 failure class, one layer up.

use std::collections::HashMap;
use std::path::PathBuf;

use serde::Deserialize;
use serde_json::Value;
use trustlayer_core::predicate::{matches_predicate, validate_predicate};

#[derive(Debug, Deserialize)]
struct Table {
    cases: Vec<Case>,
    validation_cases: Vec<ValidationCase>,
}

#[derive(Debug, Deserialize)]
struct Case {
    name: String,
    /// Absent means the dotted path did not resolve. Distinct from
    /// `actual: null`, which resolves to JSON null — the difference is exactly
    /// what `$exists` tests, so this must not collapse to `Option<Value>`
    /// defaulting to `Null`.
    #[serde(default, deserialize_with = "deserialize_some")]
    actual: Option<Value>,
    expected: Value,
    matches: bool,
}

#[derive(Debug, Deserialize)]
struct ValidationCase {
    name: String,
    expected: Value,
    valid: bool,
}

/// Distinguishes "field absent" from "field present and null".
fn deserialize_some<'de, D>(deserializer: D) -> Result<Option<Value>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    Value::deserialize(deserializer).map(Some)
}

fn table() -> Table {
    let path: PathBuf = [
        env!("CARGO_MANIFEST_DIR"),
        "..",
        "spec",
        "v0.1",
        "fixtures",
        "predicate-cases.json",
    ]
    .iter()
    .collect();
    let raw = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("reading {}: {e}", path.display()));
    serde_json::from_str(&raw).expect("predicate-cases.json parses")
}

#[test]
fn shared_evaluation_table_holds() {
    let table = table();
    assert!(!table.cases.is_empty(), "the table must not be empty");

    let mut failures: Vec<String> = Vec::new();
    for case in &table.cases {
        let got = matches_predicate(case.actual.as_ref(), &case.expected);
        if got != case.matches {
            failures.push(format!(
                "{}: expected {}, got {} (actual={:?}, expected={})",
                case.name, case.matches, got, case.actual, case.expected
            ));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn shared_validation_table_holds() {
    let table = table();
    let mut failures: Vec<String> = Vec::new();

    for case in &table.validation_cases {
        let reason = validate_predicate("p", &case.expected);
        let is_valid = reason.is_none();
        if is_valid != case.valid {
            failures.push(format!(
                "{}: expected valid={}, got {:?}",
                case.name, case.valid, reason
            ));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn case_names_are_unique() {
    // Duplicate names make a failure report ambiguous about which case broke.
    let table = table();
    let mut seen: HashMap<&str, usize> = HashMap::new();
    for case in &table.cases {
        *seen.entry(case.name.as_str()).or_default() += 1;
    }
    let dupes: Vec<&&str> = seen
        .iter()
        .filter(|(_, count)| **count > 1)
        .map(|(name, _)| name)
        .collect();
    assert!(dupes.is_empty(), "duplicate case names: {dupes:?}");
}
