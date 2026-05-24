//! Constraint Specification Language (CSL) — declarative policy DSL.
//!
//! A [`Policy`] is a named, ordered list of [`PolicyRule`]s. Each rule has a
//! [`MatchSpec`] selector and a [`crate::schema::Decision`] to return when it
//! matches. Order matters: the guardian returns the first match.
//!
//! ```json
//! {
//!   "name": "default",
//!   "rules": [
//!     {
//!       "name": "block_external_llm_with_pii",
//!       "match": {
//!         "event_type": "TOOL_CALL",
//!         "tool_name": "external_llm",
//!         "payload": { "model": "gpt-4" }
//!       },
//!       "decision": "FAIL",
//!       "reason": "External LLM cannot receive PII"
//!     }
//!   ]
//! }
//! ```
//!
//! `payload` is a [`BTreeMap`] of dotted-path → JSON literal (ADR-008).
//! See [`resolve_path`] for the path-walking rules.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::schema::{CynefinDomain, Decision, EventType};

/// A named policy: an ordered list of rules.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Policy {
    pub name: String,
    #[serde(default)]
    pub rules: Vec<PolicyRule>,
}

/// One rule inside a policy.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyRule {
    pub name: String,
    #[serde(rename = "match", default)]
    pub selector: MatchSpec,
    pub decision: Decision,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

/// Selector predicates ANDed together. An unset field matches any value.
///
/// `payload` (ADR-008) is a map of dotted-path → expected JSON literal.
/// Resolution walks `event.payload` left-to-right on `.`, with numeric
/// segments treated as array indexes. Missing paths fail to match;
/// `null` literals match `null` values only, not absent keys.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct MatchSpec {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub event_type: Option<EventType>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub agent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cynefin_domain: Option<CynefinDomain>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub payload: Option<BTreeMap<String, serde_json::Value>>,
}

/// Walk `payload` along a dotted path. Numeric segments index arrays.
/// Returns `None` if any segment is missing or traverses through a
/// non-collection value.
pub fn resolve_path<'a>(
    payload: &'a serde_json::Map<String, serde_json::Value>,
    path: &str,
) -> Option<&'a serde_json::Value> {
    let mut segments = path.split('.');
    let first = segments.next()?;
    let mut current: &serde_json::Value = payload.get(first)?;
    for seg in segments {
        current = match current {
            serde_json::Value::Object(map) => map.get(seg)?,
            serde_json::Value::Array(arr) => {
                let idx: usize = seg.parse().ok()?;
                arr.get(idx)?
            }
            _ => return None,
        };
    }
    Some(current)
}

impl Policy {
    /// Parse a policy from JSON bytes.
    pub fn from_json(bytes: &[u8]) -> crate::Result<Self> {
        serde_json::from_slice(bytes).map_err(crate::Error::InvalidPolicy)
    }

    /// Read a policy from a JSON file on disk.
    pub fn from_path(path: impl AsRef<std::path::Path>) -> crate::Result<Self> {
        let bytes = std::fs::read(path)?;
        Self::from_json(&bytes)
    }

    /// An empty policy that matches nothing — useful as a placeholder.
    pub fn empty(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            rules: Vec::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_canonical_policy() {
        let raw = r#"{
            "name": "test",
            "rules": [
                {
                    "name": "block_calc",
                    "match": { "event_type": "TOOL_CALL", "tool_name": "calculator" },
                    "decision": "FAIL",
                    "reason": "Calculator disabled"
                }
            ]
        }"#;
        let policy = Policy::from_json(raw.as_bytes()).expect("parse");
        assert_eq!(policy.name, "test");
        assert_eq!(policy.rules.len(), 1);
        let rule = &policy.rules[0];
        assert_eq!(rule.decision, Decision::Fail);
        assert_eq!(rule.selector.event_type, Some(EventType::ToolCall));
        assert_eq!(rule.selector.tool_name.as_deref(), Some("calculator"));
    }

    #[test]
    fn empty_policy_has_no_rules() {
        let p = Policy::empty("empty");
        assert!(p.rules.is_empty());
    }

    #[test]
    fn rejects_invalid_decision_value() {
        let raw = r#"{
            "name": "bad",
            "rules": [
                {"name": "r", "match": {}, "decision": "MAYBE"}
            ]
        }"#;
        assert!(Policy::from_json(raw.as_bytes()).is_err());
    }

    #[test]
    fn parses_payload_predicate_map() {
        let raw = r#"{
            "name": "test",
            "rules": [
                {
                    "name": "block_gpt4",
                    "match": {
                        "event_type": "TOOL_CALL",
                        "payload": {"model": "gpt-4", "args.temperature": 1.0}
                    },
                    "decision": "FAIL"
                }
            ]
        }"#;
        let p = Policy::from_json(raw.as_bytes()).expect("parse");
        let payload = p.rules[0].selector.payload.as_ref().expect("payload");
        assert_eq!(payload.get("model"), Some(&serde_json::json!("gpt-4")));
        assert_eq!(
            payload.get("args.temperature"),
            Some(&serde_json::json!(1.0))
        );
    }

    fn pm(json: &str) -> serde_json::Map<String, serde_json::Value> {
        serde_json::from_str(json).expect("parse payload")
    }

    #[test]
    fn resolve_path_returns_top_level_value() {
        let p = pm(r#"{"model": "gpt-4"}"#);
        assert_eq!(resolve_path(&p, "model"), Some(&serde_json::json!("gpt-4")));
    }

    #[test]
    fn resolve_path_walks_nested_objects() {
        let p = pm(r#"{"args": {"temperature": 1.0}}"#);
        assert_eq!(
            resolve_path(&p, "args.temperature"),
            Some(&serde_json::json!(1.0))
        );
    }

    #[test]
    fn resolve_path_indexes_arrays_by_numeric_segment() {
        let p = pm(r#"{"args": {"tools": ["a", "b", "c"]}}"#);
        assert_eq!(
            resolve_path(&p, "args.tools.1"),
            Some(&serde_json::json!("b"))
        );
    }

    #[test]
    fn resolve_path_returns_none_for_missing_key() {
        let p = pm(r#"{"args": {}}"#);
        assert_eq!(resolve_path(&p, "args.temperature"), None);
        assert_eq!(resolve_path(&p, "nope"), None);
    }

    #[test]
    fn resolve_path_returns_none_when_walking_into_scalar() {
        let p = pm(r#"{"model": "gpt-4"}"#);
        assert_eq!(resolve_path(&p, "model.version"), None);
    }

    #[test]
    fn resolve_path_returns_none_for_out_of_range_index() {
        let p = pm(r#"{"args": {"tools": ["a"]}}"#);
        assert_eq!(resolve_path(&p, "args.tools.5"), None);
    }

    #[test]
    fn resolve_path_returns_explicit_null() {
        let p = pm(r#"{"reason": null}"#);
        assert_eq!(resolve_path(&p, "reason"), Some(&serde_json::Value::Null));
    }
}
