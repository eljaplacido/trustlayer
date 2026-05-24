//! `cynepic-guardian` — turn an `AgentTraceEvent` + a `Policy` into a `Verdict`.
//!
//! The evaluator walks rules in declaration order and returns the first match.
//! If no rule matches, the default is `PASS` — unless the event is classified
//! `CHAOTIC`, in which case the default is `ESCALATE` (per the Cynefin model:
//! novel/crisis interactions are escalated by default).

use serde::Serialize;

use crate::policy::{MatchSpec, Policy};
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

/// Stateless evaluator. `Send + Sync` so it can be shared behind an `Arc` in a
/// hot HTTP path.
#[derive(Debug, Clone)]
pub struct CynepicGuardian {
    policy: Policy,
}

impl CynepicGuardian {
    pub fn new(policy: Policy) -> Self {
        Self { policy }
    }

    /// Return the underlying policy (useful for introspection / hot-reload).
    pub fn policy(&self) -> &Policy {
        &self.policy
    }

    /// Adjudicate one event.
    pub fn evaluate(&self, event: &AgentTraceEvent) -> Verdict {
        for rule in &self.policy.rules {
            if matches_event(&rule.selector, event) {
                return Verdict {
                    decision: rule.decision,
                    rule: Some(rule.name.clone()),
                    reason: rule.reason.clone(),
                    policy: self.policy.name.clone(),
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
            policy: self.policy.name.clone(),
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
}
