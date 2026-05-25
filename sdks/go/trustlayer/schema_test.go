package trustlayer

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

// canonical sample event — matches the JSON shape Python emits.
const pythonEmittedEvent = `{
    "trace_id": "11111111-1111-4111-8111-111111111111",
    "agent_id": "researcher-1",
    "session_id": "S1",
    "timestamp": "2026-05-07T09:00:01+00:00",
    "event_type": "TOOL_CALL",
    "cynefin_domain": "COMPLEX",
    "payload": {"tool_name": "external_llm", "tool_args": {"prompt": "hi"}},
    "metrics": {"latency_ms": 12.5, "cost_usd": 0.0015, "tokens_prompt": 150, "tokens_completion": 45}
}`

func TestUnmarshalCanonicalPythonEvent(t *testing.T) {
	var ev AgentTraceEvent
	if err := json.Unmarshal([]byte(pythonEmittedEvent), &ev); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}
	if ev.AgentID != "researcher-1" {
		t.Errorf("agent_id = %q, want researcher-1", ev.AgentID)
	}
	if ev.EventType != EventToolCall {
		t.Errorf("event_type = %q, want TOOL_CALL", ev.EventType)
	}
	if ev.CynefinDomain != CynefinComplex {
		t.Errorf("cynefin_domain = %q, want COMPLEX", ev.CynefinDomain)
	}
	if ev.Metrics.LatencyMs == nil || *ev.Metrics.LatencyMs != 12.5 {
		t.Errorf("metrics.latency_ms = %v, want 12.5", ev.Metrics.LatencyMs)
	}
	if tn, _ := ev.Payload["tool_name"].(string); tn != "external_llm" {
		t.Errorf("payload.tool_name = %v, want external_llm", ev.Payload["tool_name"])
	}
}

func TestRejectsUnknownEnvelopeField(t *testing.T) {
	raw := `{
        "trace_id": "11111111-1111-4111-8111-111111111111",
        "agent_id": "a",
        "session_id": "s",
        "timestamp": "2026-05-07T09:00:00+00:00",
        "event_type": "AGENT_START",
        "rogue": "field"
    }`
	var ev AgentTraceEvent
	err := json.Unmarshal([]byte(raw), &ev)
	if err == nil {
		t.Fatal("expected error for unknown envelope field, got nil")
	}
	if !strings.Contains(err.Error(), "rogue") {
		t.Errorf("expected error to mention the field, got %v", err)
	}
}

func TestRejectsUnknownEventType(t *testing.T) {
	raw := `{
        "trace_id": "11111111-1111-4111-8111-111111111111",
        "agent_id": "a",
        "session_id": "s",
        "timestamp": "2026-05-07T09:00:00+00:00",
        "event_type": "WHAT_IS_THIS"
    }`
	var ev AgentTraceEvent
	if err := json.Unmarshal([]byte(raw), &ev); err == nil {
		t.Fatal("expected error for unknown event_type, got nil")
	}
}

func TestRejectsUnknownCynefinDomain(t *testing.T) {
	raw := `{
        "trace_id": "11111111-1111-4111-8111-111111111111",
        "agent_id": "a",
        "session_id": "s",
        "timestamp": "2026-05-07T09:00:00+00:00",
        "event_type": "AGENT_START",
        "cynefin_domain": "SPACETIME"
    }`
	var ev AgentTraceEvent
	if err := json.Unmarshal([]byte(raw), &ev); err == nil {
		t.Fatal("expected error for unknown cynefin_domain, got nil")
	}
}

func TestDefaultsAppliedWhenAbsent(t *testing.T) {
	raw := `{
        "trace_id": "11111111-1111-4111-8111-111111111111",
        "agent_id": "a",
        "session_id": "s",
        "timestamp": "2026-05-07T09:00:00+00:00",
        "event_type": "AGENT_START"
    }`
	var ev AgentTraceEvent
	if err := json.Unmarshal([]byte(raw), &ev); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if ev.CynefinDomain != CynefinDisorder {
		t.Errorf("default cynefin = %q, want DISORDER", ev.CynefinDomain)
	}
	if ev.Payload == nil || len(ev.Payload) != 0 {
		t.Errorf("default payload = %v, want empty map", ev.Payload)
	}
}

func TestRoundTripsThroughJSON(t *testing.T) {
	ev := NewEvent("a", "s", EventToolCall,
		WithPayload(map[string]any{"tool_name": "calc"}),
		WithCynefin(CynefinClear),
	)
	body, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var back AgentTraceEvent
	if err := json.Unmarshal(body, &back); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if back.AgentID != "a" || back.SessionID != "s" || back.EventType != EventToolCall {
		t.Errorf("round-trip lost fields: %+v", back)
	}
	if back.CynefinDomain != CynefinClear {
		t.Errorf("cynefin lost: %q", back.CynefinDomain)
	}
}

func TestNewEventGeneratesFreshTraceID(t *testing.T) {
	a := NewEvent("a", "s", EventAgentStart)
	b := NewEvent("a", "s", EventAgentStart)
	if a.TraceID == b.TraceID {
		t.Error("expected distinct UUIDs on each NewEvent call")
	}
	if a.TraceID == uuid.Nil {
		t.Error("expected non-nil UUID")
	}
}

func TestEventTypeEnumValues(t *testing.T) {
	cases := []EventType{
		EventAgentStart,
		EventToolCall,
		EventToolResult,
		EventLLMCall,
		EventPolicyCheck,
		EventHumanEscalation,
		EventAgentEnd,
	}
	for _, et := range cases {
		body, err := json.Marshal(et)
		if err != nil {
			t.Fatalf("marshal %q: %v", et, err)
		}
		// Marshalled form is just "VALUE" — uppercase, snake_case.
		s := strings.Trim(string(body), `"`)
		if s != string(et) {
			t.Errorf("marshal(%q) = %q", et, s)
		}
	}
}

func TestTimestampEncodesWithOffset(t *testing.T) {
	ev := NewEvent("a", "s", EventAgentStart,
		WithTimestamp(time.Date(2026, 5, 24, 9, 0, 0, 0, time.UTC)),
	)
	body, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if !strings.Contains(string(body), "2026-05-24T09:00:00Z") {
		t.Errorf("expected RFC3339 timestamp with Z offset, got %s", body)
	}
}

func TestMetricsPreservesUnknownKeys(t *testing.T) {
	raw := `{"latency_ms": 1.0, "custom_metric": 42}`
	var m Metrics
	if err := json.Unmarshal([]byte(raw), &m); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if got := m.Extra["custom_metric"]; got != float64(42) {
		t.Errorf("Extra[custom_metric] = %v, want 42", got)
	}
	body, err := json.Marshal(m)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if !strings.Contains(string(body), `"custom_metric":42`) {
		t.Errorf("round-trip lost custom key: %s", body)
	}
}
