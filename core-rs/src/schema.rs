//! Rust mirror of `docs/SCHEMA.md` — `AgentTraceEvent` and friends.
//!
//! Serialization is wire-identical to the Python (`pydantic`) and TypeScript
//! (`zod`) implementations. Cross-language round-trip is verified in
//! `tests/cross_language.rs`.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Event types emitted by an instrumented agent.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EventType {
    AgentStart,
    ToolCall,
    ToolResult,
    LlmCall,
    PolicyCheck,
    HumanEscalation,
    AgentEnd,
}

/// Cynefin classification of the decision context.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash, Default)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CynefinDomain {
    Clear,
    Complicated,
    Complex,
    Chaotic,
    #[default]
    Disorder,
}

/// Result of a policy check — also reused as the [`crate::guardian`] decision.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Decision {
    Pass,
    Fail,
    Escalate,
}

/// Cost/latency metrics that accompany an event. Extra keys ride along.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Metrics {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub latency_ms: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost_usd: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tokens_prompt: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tokens_completion: Option<u32>,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Trace envelope emitted by an instrumented agent.
///
/// The envelope is strict (`deny_unknown_fields`) to catch wire drift early;
/// the `payload` itself is intentionally open-ended.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AgentTraceEvent {
    pub trace_id: Uuid,
    pub agent_id: String,
    pub session_id: String,
    pub timestamp: DateTime<Utc>,
    pub event_type: EventType,
    #[serde(default)]
    pub cynefin_domain: CynefinDomain,
    #[serde(default)]
    pub payload: serde_json::Map<String, serde_json::Value>,
    #[serde(default)]
    pub metrics: Metrics,
}

impl AgentTraceEvent {
    /// Look up `payload.tool_name` if it exists and is a string.
    pub fn tool_name(&self) -> Option<&str> {
        self.payload.get("tool_name").and_then(|v| v.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_minimal_event() {
        let raw = r#"{
            "trace_id": "11111111-1111-4111-8111-111111111111",
            "agent_id": "a",
            "session_id": "s",
            "timestamp": "2026-05-13T10:00:00+00:00",
            "event_type": "AGENT_START"
        }"#;
        let event: AgentTraceEvent = serde_json::from_str(raw).expect("parse");
        assert_eq!(event.agent_id, "a");
        assert_eq!(event.event_type, EventType::AgentStart);
        assert_eq!(event.cynefin_domain, CynefinDomain::Disorder);
        let json = serde_json::to_string(&event).expect("serialise");
        let again: AgentTraceEvent = serde_json::from_str(&json).expect("re-parse");
        assert_eq!(event.trace_id, again.trace_id);
    }

    #[test]
    fn rejects_unknown_top_level_field() {
        let raw = r#"{
            "trace_id": "11111111-1111-4111-8111-111111111111",
            "agent_id": "a",
            "session_id": "s",
            "timestamp": "2026-05-13T10:00:00+00:00",
            "event_type": "AGENT_START",
            "rogue": "field"
        }"#;
        assert!(serde_json::from_str::<AgentTraceEvent>(raw).is_err());
    }

    #[test]
    fn enum_serialises_screaming_snake_case() {
        assert_eq!(
            serde_json::to_string(&EventType::ToolCall).unwrap(),
            "\"TOOL_CALL\""
        );
        assert_eq!(
            serde_json::to_string(&Decision::Escalate).unwrap(),
            "\"ESCALATE\""
        );
        assert_eq!(
            serde_json::to_string(&CynefinDomain::Disorder).unwrap(),
            "\"DISORDER\""
        );
    }

    #[test]
    fn tool_name_helper_returns_string() {
        let raw = r#"{
            "trace_id": "11111111-1111-4111-8111-111111111111",
            "agent_id": "a",
            "session_id": "s",
            "timestamp": "2026-05-13T10:00:00+00:00",
            "event_type": "TOOL_CALL",
            "payload": {"tool_name": "calc", "tool_args": {"x": 1}}
        }"#;
        let event: AgentTraceEvent = serde_json::from_str(raw).expect("parse");
        assert_eq!(event.tool_name(), Some("calc"));
    }

    #[test]
    fn metrics_extra_fields_passthrough() {
        let raw = r#"{"latency_ms": 12.5, "custom": 99}"#;
        let m: Metrics = serde_json::from_str(raw).expect("parse");
        assert_eq!(m.latency_ms, Some(12.5));
        assert_eq!(m.extra.get("custom").and_then(|v| v.as_i64()), Some(99));
    }
}
