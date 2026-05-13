//! Verify the Rust schema parses JSON emitted by the Python SDK and that
//! the guardian returns a decision the Python client can deserialize.

use trustlayer_core::{
    AgentTraceEvent, CynefinDomain, CynepicGuardian, Decision, EventType, MatchSpec, Policy,
    PolicyRule,
};

/// Snapshot of an event produced by `AgentTraceEvent.model_dump_json()` in the
/// Python SDK (Pydantic v2). The exact shape — UUIDs, timestamps with offset,
/// SCREAMING_SNAKE_CASE enums, payload dict — is the contract.
const PY_EVENT_SAMPLE: &str = r#"{
    "trace_id": "11111111-1111-4111-8111-111111111111",
    "agent_id": "researcher-1",
    "session_id": "S1",
    "timestamp": "2026-05-07T09:00:01+00:00",
    "event_type": "TOOL_CALL",
    "cynefin_domain": "COMPLEX",
    "payload": {"tool_name": "external_llm", "tool_args": {"prompt": "hello"}},
    "metrics": {"latency_ms": 12.5, "cost_usd": 0.0015, "tokens_prompt": 150, "tokens_completion": 45}
}"#;

#[test]
fn parses_pydantic_emitted_event() {
    let event: AgentTraceEvent = serde_json::from_str(PY_EVENT_SAMPLE).expect("parse");
    assert_eq!(event.event_type, EventType::ToolCall);
    assert_eq!(event.cynefin_domain, CynefinDomain::Complex);
    assert_eq!(event.tool_name(), Some("external_llm"));
    assert_eq!(event.metrics.latency_ms, Some(12.5));
}

#[test]
fn parses_zod_emitted_event_with_default_metrics() {
    let raw = r#"{
        "trace_id": "22222222-2222-4222-8222-222222222222",
        "agent_id": "ts-agent",
        "session_id": "S2",
        "timestamp": "2026-05-07T09:00:00.000Z",
        "event_type": "AGENT_START",
        "cynefin_domain": "DISORDER",
        "payload": {},
        "metrics": {}
    }"#;
    let event: AgentTraceEvent = serde_json::from_str(raw).expect("parse");
    assert_eq!(event.event_type, EventType::AgentStart);
    assert_eq!(event.metrics.latency_ms, None);
}

#[test]
fn guardian_blocks_external_llm() {
    let policy = Policy {
        name: "default".to_string(),
        rules: vec![PolicyRule {
            name: "block_external_llm".to_string(),
            selector: MatchSpec {
                event_type: Some(EventType::ToolCall),
                tool_name: Some("external_llm".to_string()),
                ..Default::default()
            },
            decision: Decision::Fail,
            reason: Some("PII".to_string()),
        }],
    };
    let event: AgentTraceEvent = serde_json::from_str(PY_EVENT_SAMPLE).unwrap();
    let verdict = CynepicGuardian::new(policy).evaluate(&event);
    assert_eq!(verdict.decision, Decision::Fail);
    assert_eq!(verdict.rule.as_deref(), Some("block_external_llm"));
    assert_eq!(verdict.policy, "default");

    // Serialise -> assert the JSON shape the Python SDK will receive.
    let verdict_json = serde_json::to_value(&verdict).unwrap();
    assert_eq!(verdict_json["decision"], "FAIL");
    assert_eq!(verdict_json["rule"], "block_external_llm");
    assert_eq!(verdict_json["policy"], "default");
}

#[test]
fn loads_default_policy_from_repo() {
    let policy = Policy::from_path("policies/default.json").expect("read policy");
    assert_eq!(policy.name, "default");
    assert!(!policy.rules.is_empty());
}
