//! Verify the Rust schema parses JSON emitted by the Python SDK and that
//! the guardian returns a decision the Python client can deserialize.
//!
//! Slice 4b extends this to the Go SDK: the conformance fixtures under
//! `spec/v0.1/fixtures/` are loaded and asserted to round-trip through
//! the Rust envelope without losses, proving wire-format parity
//! end-to-end. Phase 8 slice 8.0 adds Art. 50 fixtures for
//! `DISCLOSURE_SHOWN` and `CONTENT_MARKED`, and globs the directory so a
//! newly committed fixture is covered without editing this file.

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

/// ADR-008: Pydantic-emitted payload + Rust-side payload predicate must
/// agree end-to-end. The Python SDK uses `json.dumps`-equivalent
/// serialisation, so the wire literals (`"gpt-4"`, `1.0`) must compare
/// equal to JSON literals in the policy.
#[test]
fn guardian_payload_predicate_against_pydantic_event() {
    const EVENT: &str = r#"{
        "trace_id": "33333333-3333-4333-8333-333333333333",
        "agent_id": "researcher-1",
        "session_id": "S1",
        "timestamp": "2026-05-24T09:00:00+00:00",
        "event_type": "LLM_CALL",
        "cynefin_domain": "COMPLEX",
        "payload": {"model": "gpt-4", "args": {"temperature": 1.0, "tools": ["shell"]}},
        "metrics": {}
    }"#;
    let event: AgentTraceEvent = serde_json::from_str(EVENT).expect("parse");

    let mut payload = std::collections::BTreeMap::new();
    payload.insert("model".to_string(), serde_json::json!("gpt-4"));
    payload.insert("args.temperature".to_string(), serde_json::json!(1.0));
    payload.insert("args.tools.0".to_string(), serde_json::json!("shell"));

    let policy = Policy {
        name: "test".into(),
        rules: vec![PolicyRule {
            name: "block_gpt4_with_shell".into(),
            selector: MatchSpec {
                event_type: Some(EventType::LlmCall),
                payload: Some(payload),
                ..Default::default()
            },
            decision: Decision::Fail,
            reason: None,
        }],
    };
    let verdict = CynepicGuardian::new(policy).evaluate(&event);
    assert_eq!(verdict.decision, Decision::Fail);
    assert_eq!(verdict.rule.as_deref(), Some("block_gpt4_with_shell"));
}

/// ADR-011 wire-format parity: the canonical fixture produced by the
/// Go SDK MUST parse through the same Rust envelope as Python and
/// TypeScript. We load `spec/v0.1/fixtures/event-canonical-go.json` —
/// committed alongside the Go SDK and reproducible via
/// `cd sdks/go && go run ./examples/conformance`.
#[test]
fn parses_go_emitted_conformance_fixture() {
    // The test runs with the working directory set to `core-rs/`, so
    // step up two levels to find the spec fixture.
    let path = "../spec/v0.1/fixtures/event-canonical-go.json";
    let bytes = std::fs::read(path).unwrap_or_else(|e| panic!("read fixture at {path}: {e}"));
    let event: AgentTraceEvent = serde_json::from_slice(&bytes).expect("parse Go-emitted fixture");

    assert_eq!(event.agent_id, "researcher-1");
    assert_eq!(event.session_id, "S1");
    assert_eq!(event.event_type, EventType::ToolCall);
    assert_eq!(event.cynefin_domain, CynefinDomain::Complex);
    assert_eq!(event.tool_name(), Some("external_llm"));
    assert_eq!(event.metrics.latency_ms, Some(12.5));
    assert_eq!(event.metrics.cost_usd, Some(0.0015));
    assert_eq!(event.metrics.tokens_prompt, Some(150));
    assert_eq!(event.metrics.tokens_completion, Some(45));

    // The payload's `model` field is the one ADR-008 payload predicates
    // can match against; verify it survived the Go → Rust hop.
    assert_eq!(
        event.payload.get("model").and_then(|v| v.as_str()),
        Some("gpt-4")
    );
}

/// Load a committed conformance fixture. The test runs with the working
/// directory set to `core-rs/`, so step up one level to reach `spec/`.
fn load_fixture(name: &str) -> AgentTraceEvent {
    let path = format!("../spec/v0.1/fixtures/{name}");
    let bytes = std::fs::read(&path).unwrap_or_else(|e| panic!("read fixture at {path}: {e}"));
    serde_json::from_slice(&bytes).unwrap_or_else(|e| panic!("parse fixture {path}: {e}"))
}

/// Every committed **event** fixture MUST parse through the strict envelope (W1).
///
/// The fixtures README promises this test loads every event fixture in the
/// directory; globbing rather than naming files is what makes that true, so a
/// fixture added without a matching assertion still cannot rot.
///
/// Scoped to the `event-` prefix the README defines
/// (`event-<subject>-<lang>.json`) because the directory also holds conformance
/// tables that are deliberately not events — `predicate-cases.json` is a shared
/// table of predicate cases, not an `AgentTraceEvent`, and asserting it against
/// the envelope tests nothing.
#[test]
fn every_committed_event_fixture_parses() {
    let dir = "../spec/v0.1/fixtures";
    let mut checked = 0;
    for entry in std::fs::read_dir(dir).expect("read fixtures dir") {
        let path = entry.expect("dir entry").path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let is_event_fixture = path
            .file_name()
            .and_then(|n| n.to_str())
            .is_some_and(|n| n.starts_with("event-"));
        if !is_event_fixture {
            continue;
        }
        let bytes = std::fs::read(&path).expect("read fixture");
        let _: AgentTraceEvent = serde_json::from_slice(&bytes).unwrap_or_else(|e| {
            panic!("fixture {} failed the strict envelope: {e}", path.display())
        });
        checked += 1;
    }
    assert!(
        checked >= 3,
        "expected at least 3 event fixtures, found {checked}"
    );
}

/// EU AI Act Art. 50 event types must round-trip across all four SDKs.
/// Asserting against the committed Go-emitted fixture (rather than an
/// inline literal) means the bytes under test are the bytes an SDK
/// actually produces.
#[test]
fn parses_disclosure_shown_fixture() {
    let event = load_fixture("event-disclosure-shown-go.json");

    assert_eq!(event.event_type, EventType::DisclosureShown);
    assert_eq!(event.cynefin_domain, CynefinDomain::Clear);
    assert_eq!(event.agent_id, "art50-agent");
    // spec §2.8: `disclosure_type` is REQUIRED and drives the Art. 50
    // control catalog's `payload_filters`.
    assert_eq!(
        event
            .payload
            .get("disclosure_type")
            .and_then(|v| v.as_str()),
        Some("ai_interaction")
    );
    assert_eq!(
        event.payload.get("locale").and_then(|v| v.as_str()),
        Some("en-GB")
    );
}

#[test]
fn parses_content_marked_fixture() {
    let event = load_fixture("event-content-marked-go.json");

    assert_eq!(event.event_type, EventType::ContentMarked);
    assert_eq!(event.cynefin_domain, CynefinDomain::Clear);
    assert_eq!(
        event.payload.get("marking_type").and_then(|v| v.as_str()),
        Some("c2pa")
    );

    // spec §2.9: nested `verification` must survive the round trip — it is
    // what separates a marking claim from a verified marking.
    let verification = event
        .payload
        .get("verification")
        .expect("verification block present");
    assert_eq!(
        verification.get("verified").and_then(|v| v.as_bool()),
        Some(true)
    );
    assert_eq!(
        verification.get("method").and_then(|v| v.as_str()),
        Some("c2pa")
    );
}

#[test]
fn new_event_types_serialise_screaming_snake_case() {
    assert_eq!(
        serde_json::to_string(&EventType::DisclosureShown).unwrap(),
        "\"DISCLOSURE_SHOWN\""
    );
    assert_eq!(
        serde_json::to_string(&EventType::ContentMarked).unwrap(),
        "\"CONTENT_MARKED\""
    );
}
