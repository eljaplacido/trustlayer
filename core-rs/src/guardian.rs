//! `cynepic-guardian` — turn an `AgentTraceEvent` + a `Policy` into a `Verdict`.
//!
//! The evaluator walks rules in declaration order and returns the first match.
//! If no rule matches, the default is `PASS` — unless the event is classified
//! `CHAOTIC`, in which case the default is `ESCALATE` (per the Cynefin model:
//! novel/crisis interactions are escalated by default).
//!
//! Policy storage lives behind an [`ArcSwap`] (ADR-009) so the watcher in
//! [`crate::policy_watch`] can replace it atomically without blocking the
//! `/v1/check` hot path. `Arc<Policy>` clones are cheap reference bumps.

use std::sync::Arc;

use arc_swap::ArcSwap;
use serde::Serialize;

use crate::policy::{resolve_path, MatchSpec, Policy};
use crate::schema::{AgentTraceEvent, CynefinDomain, Decision};

/// The guardian's adjudication for one event.
#[derive(Debug, Clone, Serialize)]
pub struct Verdict {
    pub decision: Decision,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rule: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    pub policy: String,
}

/// Stateless evaluator with a wait-free policy swap.
///
/// `evaluate` does a single relaxed atomic load on the policy pointer per
/// call (via `ArcSwap`), so concurrent hot-reload via [`replace_policy`] is
/// safe and uncontended.
#[derive(Debug)]
pub struct CynepicGuardian {
    policy: ArcSwap<Policy>,
}

impl CynepicGuardian {
    pub fn new(policy: Policy) -> Self {
        Self {
            policy: ArcSwap::from_pointee(policy),
        }
    }

    /// Return a snapshot of the active policy. Cheap — bumps a refcount.
    pub fn policy(&self) -> Arc<Policy> {
        self.policy.load_full()
    }

    /// Atomically swap in a new policy (ADR-009). Concurrent `evaluate` calls
    /// either see the old policy in full or the new one in full — never a torn
    /// mix.
    pub fn replace_policy(&self, policy: Policy) {
        self.policy.store(Arc::new(policy));
    }

    /// Adjudicate one event.
    pub fn evaluate(&self, event: &AgentTraceEvent) -> Verdict {
        let policy = self.policy.load();
        for rule in &policy.rules {
            if matches_event(&rule.selector, event) {
                return Verdict {
                    decision: rule.decision,
                    rule: Some(rule.name.clone()),
                    reason: rule.reason.clone(),
                    policy: policy.name.clone(),
                };
            }
        }
        let chaotic_default = matches!(event.cynefin_domain, CynefinDomain::Chaotic);
        Verdict {
            decision: if chaotic_default {
                Decision::Escalate
            } else {
                Decision::Pass
            },
            rule: None,
            reason: chaotic_default
                .then(|| "CHAOTIC domain - no rule matched; escalating by default".to_string()),
            policy: policy.name.clone(),
        }
    }
}

fn matches_event(selector: &MatchSpec, event: &AgentTraceEvent) -> bool {
    if let Some(et) = selector.event_type {
        if et != event.event_type {
            return false;
        }
    }
    if let Some(ref aid) = selector.agent_id {
        if aid != &event.agent_id {
            return false;
        }
    }
    if let Some(cd) = selector.cynefin_domain {
        if cd != event.cynefin_domain {
            return false;
        }
    }
    if let Some(ref tn) = selector.tool_name {
        if event.tool_name() != Some(tn.as_str()) {
            return false;
        }
    }
    if let Some(ref predicates) = selector.payload {
        // ADR-008: every dotted path must resolve to a value deep-equal to the
        // expected JSON literal. Missing paths never match.
        for (path, expected) in predicates {
            match resolve_path(&event.payload, path) {
                Some(actual) if actual == expected => continue,
                _ => return false,
            }
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::PolicyRule;
    use crate::schema::{CynefinDomain, EventType};
    use chrono::Utc;
    use uuid::Uuid;

    fn event(
        event_type: EventType,
        tool_name: Option<&str>,
        domain: CynefinDomain,
    ) -> AgentTraceEvent {
        let mut payload = serde_json::Map::new();
        if let Some(name) = tool_name {
            payload.insert(
                "tool_name".to_string(),
                serde_json::Value::String(name.to_string()),
            );
        }
        AgentTraceEvent {
            trace_id: Uuid::nil(),
            agent_id: "a".to_string(),
            session_id: "s".to_string(),
            timestamp: Utc::now(),
            event_type,
            cynefin_domain: domain,
            payload,
            metrics: Default::default(),
        }
    }

    fn policy(rules: Vec<PolicyRule>) -> Policy {
        Policy {
            name: "test".to_string(),
            rules,
        }
    }

    #[test]
    fn empty_policy_returns_pass() {
        let g = CynepicGuardian::new(Policy::empty("empty"));
        let v = g.evaluate(&event(
            EventType::ToolCall,
            Some("calc"),
            CynefinDomain::Clear,
        ));
        assert_eq!(v.decision, Decision::Pass);
        assert_eq!(v.rule, None);
        assert_eq!(v.policy, "empty");
    }

    #[test]
    fn first_matching_rule_wins() {
        let g = CynepicGuardian::new(policy(vec![
            PolicyRule {
                name: "first".into(),
                selector: MatchSpec {
                    tool_name: Some("calc".into()),
                    ..Default::default()
                },
                decision: Decision::Fail,
                reason: Some("blocked".into()),
            },
            PolicyRule {
                name: "second".into(),
                selector: MatchSpec::default(),
                decision: Decision::Escalate,
                reason: None,
            },
        ]));
        let v = g.evaluate(&event(
            EventType::ToolCall,
            Some("calc"),
            CynefinDomain::Clear,
        ));
        assert_eq!(v.decision, Decision::Fail);
        assert_eq!(v.rule.as_deref(), Some("first"));
        assert_eq!(v.reason.as_deref(), Some("blocked"));
    }

    #[test]
    fn unmatched_event_passes_by_default() {
        let g = CynepicGuardian::new(policy(vec![PolicyRule {
            name: "calc-only".into(),
            selector: MatchSpec {
                tool_name: Some("calc".into()),
                ..Default::default()
            },
            decision: Decision::Fail,
            reason: None,
        }]));
        let v = g.evaluate(&event(
            EventType::ToolCall,
            Some("web"),
            CynefinDomain::Clear,
        ));
        assert_eq!(v.decision, Decision::Pass);
    }

    #[test]
    fn chaotic_domain_escalates_by_default() {
        let g = CynepicGuardian::new(Policy::empty("empty"));
        let v = g.evaluate(&event(
            EventType::ToolCall,
            Some("calc"),
            CynefinDomain::Chaotic,
        ));
        assert_eq!(v.decision, Decision::Escalate);
        assert!(v.reason.as_deref().unwrap_or("").contains("CHAOTIC"));
    }

    #[test]
    fn explicit_rule_overrides_chaotic_default() {
        let g = CynepicGuardian::new(policy(vec![PolicyRule {
            name: "allow-calc".into(),
            selector: MatchSpec {
                tool_name: Some("calc".into()),
                ..Default::default()
            },
            decision: Decision::Pass,
            reason: None,
        }]));
        let v = g.evaluate(&event(
            EventType::ToolCall,
            Some("calc"),
            CynefinDomain::Chaotic,
        ));
        assert_eq!(v.decision, Decision::Pass);
    }

    #[test]
    fn match_spec_anding_requires_all_specified_fields() {
        let g = CynepicGuardian::new(policy(vec![PolicyRule {
            name: "calc-on-agent-a".into(),
            selector: MatchSpec {
                tool_name: Some("calc".into()),
                agent_id: Some("a".into()),
                ..Default::default()
            },
            decision: Decision::Fail,
            reason: None,
        }]));
        // Same tool, different agent -> no match.
        let mut evt = event(EventType::ToolCall, Some("calc"), CynefinDomain::Clear);
        evt.agent_id = "b".to_string();
        let v = g.evaluate(&evt);
        assert_eq!(v.decision, Decision::Pass);
    }

    #[test]
    fn cynefin_domain_match_filter() {
        let g = CynepicGuardian::new(policy(vec![PolicyRule {
            name: "complex-only-escalate".into(),
            selector: MatchSpec {
                cynefin_domain: Some(CynefinDomain::Complex),
                ..Default::default()
            },
            decision: Decision::Escalate,
            reason: Some("complex domain".into()),
        }]));
        let v = g.evaluate(&event(EventType::LlmCall, None, CynefinDomain::Complex));
        assert_eq!(v.decision, Decision::Escalate);
        let v = g.evaluate(&event(EventType::LlmCall, None, CynefinDomain::Clear));
        assert_eq!(v.decision, Decision::Pass);
    }

    // ─── ADR-008: payload predicates ────────────────────────────────────

    use std::collections::BTreeMap;

    fn rule_with_payload(
        predicates: &[(&str, serde_json::Value)],
        decision: Decision,
    ) -> PolicyRule {
        let map: BTreeMap<String, serde_json::Value> = predicates
            .iter()
            .map(|(k, v)| ((*k).to_string(), v.clone()))
            .collect();
        PolicyRule {
            name: "payload-rule".into(),
            selector: MatchSpec {
                payload: Some(map),
                ..Default::default()
            },
            decision,
            reason: None,
        }
    }

    fn event_with_payload(value: serde_json::Value) -> AgentTraceEvent {
        let serde_json::Value::Object(map) = value else {
            panic!("expected object");
        };
        AgentTraceEvent {
            trace_id: Uuid::nil(),
            agent_id: "a".to_string(),
            session_id: "s".to_string(),
            timestamp: Utc::now(),
            event_type: EventType::ToolCall,
            cynefin_domain: CynefinDomain::Clear,
            payload: map,
            metrics: Default::default(),
        }
    }

    #[test]
    fn payload_predicate_matches_flat_string() {
        let g = CynepicGuardian::new(policy(vec![rule_with_payload(
            &[("model", serde_json::json!("gpt-4"))],
            Decision::Fail,
        )]));
        let v = g.evaluate(&event_with_payload(serde_json::json!({"model": "gpt-4"})));
        assert_eq!(v.decision, Decision::Fail);
    }

    #[test]
    fn payload_predicate_string_value_mismatch_does_not_match() {
        let g = CynepicGuardian::new(policy(vec![rule_with_payload(
            &[("model", serde_json::json!("gpt-4"))],
            Decision::Fail,
        )]));
        let v = g.evaluate(&event_with_payload(
            serde_json::json!({"model": "claude-opus"}),
        ));
        assert_eq!(v.decision, Decision::Pass);
    }

    #[test]
    fn payload_predicate_walks_dotted_path() {
        let g = CynepicGuardian::new(policy(vec![rule_with_payload(
            &[("args.temperature", serde_json::json!(1.0))],
            Decision::Escalate,
        )]));
        let v = g.evaluate(&event_with_payload(
            serde_json::json!({"args": {"temperature": 1.0}}),
        ));
        assert_eq!(v.decision, Decision::Escalate);
    }

    #[test]
    fn payload_predicate_indexes_arrays() {
        let g = CynepicGuardian::new(policy(vec![rule_with_payload(
            &[("args.tools.0", serde_json::json!("shell"))],
            Decision::Fail,
        )]));
        let v = g.evaluate(&event_with_payload(
            serde_json::json!({"args": {"tools": ["shell", "browser"]}}),
        ));
        assert_eq!(v.decision, Decision::Fail);
    }

    #[test]
    fn payload_predicate_missing_path_does_not_match() {
        let g = CynepicGuardian::new(policy(vec![rule_with_payload(
            &[("model", serde_json::json!("gpt-4"))],
            Decision::Fail,
        )]));
        let v = g.evaluate(&event_with_payload(
            serde_json::json!({"tool_name": "calc"}),
        ));
        assert_eq!(v.decision, Decision::Pass);
    }

    #[test]
    fn payload_predicate_anding_requires_all_paths() {
        let g = CynepicGuardian::new(policy(vec![rule_with_payload(
            &[
                ("model", serde_json::json!("gpt-4")),
                ("args.temperature", serde_json::json!(1.0)),
            ],
            Decision::Fail,
        )]));
        // both match -> fires
        let v = g.evaluate(&event_with_payload(serde_json::json!({
            "model": "gpt-4",
            "args": {"temperature": 1.0}
        })));
        assert_eq!(v.decision, Decision::Fail);
        // only one matches -> doesn't fire
        let v = g.evaluate(&event_with_payload(serde_json::json!({
            "model": "gpt-4",
            "args": {"temperature": 0.0}
        })));
        assert_eq!(v.decision, Decision::Pass);
    }

    #[test]
    fn payload_predicate_null_vs_absent_distinction() {
        // Expecting `null` should match an explicit null, not a missing key.
        let g = CynepicGuardian::new(policy(vec![rule_with_payload(
            &[("reason", serde_json::Value::Null)],
            Decision::Fail,
        )]));
        let v = g.evaluate(&event_with_payload(serde_json::json!({"reason": null})));
        assert_eq!(v.decision, Decision::Fail);
        let v = g.evaluate(&event_with_payload(serde_json::json!({})));
        assert_eq!(v.decision, Decision::Pass);
    }

    #[test]
    fn payload_predicate_ands_with_event_type() {
        let g = CynepicGuardian::new(policy(vec![PolicyRule {
            name: "tool-call-with-gpt4".into(),
            selector: MatchSpec {
                event_type: Some(EventType::ToolCall),
                payload: Some(BTreeMap::from([(
                    "model".to_string(),
                    serde_json::json!("gpt-4"),
                )])),
                ..Default::default()
            },
            decision: Decision::Fail,
            reason: None,
        }]));
        let v = g.evaluate(&event_with_payload(serde_json::json!({"model": "gpt-4"})));
        assert_eq!(v.decision, Decision::Fail);
        // Wrong event_type — payload matches, but the AND with event_type fails.
        let mut evt = event_with_payload(serde_json::json!({"model": "gpt-4"}));
        evt.event_type = EventType::AgentStart;
        let v = g.evaluate(&evt);
        assert_eq!(v.decision, Decision::Pass);
    }
}
