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
//!       "match": { "event_type": "TOOL_CALL", "tool_name": "external_llm" },
//!       "decision": "FAIL",
//!       "reason": "External LLM cannot receive PII"
//!     }
//!   ]
//! }
//! ```

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
}
