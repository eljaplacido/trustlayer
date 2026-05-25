package trustlayer

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
)

// captureClient records every emitted event so tests can assert the
// trace stream the Tracer produces.
type captureClient struct {
	mu     sync.Mutex
	events []AgentTraceEvent
}

func (c *captureClient) handler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		c.mu.Lock()
		defer c.mu.Unlock()
		// /v1/events accepts a single event OR a batch; the SDK only
		// ever sends single events here.
		var single AgentTraceEvent
		if err := json.Unmarshal(body, &single); err == nil && single.EventType != "" {
			c.events = append(c.events, single)
			w.WriteHeader(http.StatusOK)
			return
		}
		var batch []AgentTraceEvent
		if err := json.Unmarshal(body, &batch); err == nil {
			c.events = append(c.events, batch...)
		}
		w.WriteHeader(http.StatusOK)
	}
}

func (c *captureClient) snapshot() []AgentTraceEvent {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]AgentTraceEvent, len(c.events))
	copy(out, c.events)
	return out
}

func TestTracerEmitPassesThroughToClient(t *testing.T) {
	cap := &captureClient{}
	srv := httptest.NewServer(cap.handler())
	defer srv.Close()
	client, _ := NewClient(ClientOptions{Endpoint: srv.URL})
	tracer := NewTracer(client, "researcher-1", "S1")

	ev := NewEvent("researcher-1", "S1", EventAgentStart)
	if err := tracer.Emit(context.Background(), ev); err != nil {
		t.Fatalf("emit: %v", err)
	}
	events := cap.snapshot()
	if len(events) != 1 || events[0].EventType != EventAgentStart {
		t.Errorf("expected AGENT_START, got %+v", events)
	}
}

func TestTracerToolCallEmitsStartAndResult(t *testing.T) {
	cap := &captureClient{}
	srv := httptest.NewServer(cap.handler())
	defer srv.Close()
	client, _ := NewClient(ClientOptions{Endpoint: srv.URL})
	tracer := NewTracer(client, "a", "s")

	var result any
	var err error
	close := tracer.ToolCall(context.Background(), "calc", map[string]any{"x": 1}, &result, &err)
	result = 42
	close()

	events := cap.snapshot()
	if len(events) != 2 {
		t.Fatalf("expected 2 events, got %d: %+v", len(events), events)
	}
	if events[0].EventType != EventToolCall {
		t.Errorf("first event = %q, want TOOL_CALL", events[0].EventType)
	}
	if events[1].EventType != EventToolResult {
		t.Errorf("second event = %q, want TOOL_RESULT", events[1].EventType)
	}
	if events[1].Payload["result"] != 42.0 { // JSON round-trip turns int → float64
		t.Errorf("result payload = %v, want 42", events[1].Payload["result"])
	}
	if events[1].Metrics.LatencyMs == nil {
		t.Error("expected TOOL_RESULT to carry latency_ms")
	}
}

func TestTracerToolCallCapturesError(t *testing.T) {
	cap := &captureClient{}
	srv := httptest.NewServer(cap.handler())
	defer srv.Close()
	client, _ := NewClient(ClientOptions{Endpoint: srv.URL})
	tracer := NewTracer(client, "a", "s")

	var result any
	var err error
	close := tracer.ToolCall(context.Background(), "calc", nil, &result, &err)
	err = io.EOF
	close()

	events := cap.snapshot()
	if events[1].Payload["error"] != "EOF" {
		t.Errorf("error payload = %v, want 'EOF'", events[1].Payload["error"])
	}
}

func TestTracerCheckRequiresGuardian(t *testing.T) {
	cap := &captureClient{}
	srv := httptest.NewServer(cap.handler())
	defer srv.Close()
	client, _ := NewClient(ClientOptions{Endpoint: srv.URL})
	tracer := NewTracer(client, "a", "s")

	if _, err := tracer.Check(context.Background(), "calc", nil, nil); err == nil {
		t.Error("expected error when TracerCheck.Guardian is nil")
	}
	if _, err := tracer.Check(context.Background(), "calc", nil, &TracerCheck{}); err == nil {
		t.Error("expected error when TracerCheck.Guardian is nil (empty opts)")
	}
}

func TestTracerCheckEmitsToolCallAndPolicyCheck(t *testing.T) {
	// One server captures the ingest stream, another plays the guardian.
	ingest := &captureClient{}
	ingestSrv := httptest.NewServer(ingest.handler())
	defer ingestSrv.Close()
	guardianSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{
            "decision": "FAIL",
            "rule": "block_external_llm",
            "reason": "PII",
            "policy": "default"
        }`))
	}))
	defer guardianSrv.Close()

	client, _ := NewClient(ClientOptions{Endpoint: ingestSrv.URL})
	guardian, _ := NewGuardian(GuardianOptions{Endpoint: guardianSrv.URL, PolicyName: "default"})
	tracer := NewTracer(client, "researcher-1", "S1")

	v, err := tracer.Check(context.Background(), "external_llm",
		map[string]any{"prompt": "hi"},
		&TracerCheck{Guardian: guardian, PolicyName: "default", CynefinDomain: CynefinComplex},
	)
	if err != nil {
		t.Fatalf("check: %v", err)
	}
	if v.Decision != DecisionFail {
		t.Errorf("verdict.Decision = %q, want FAIL", v.Decision)
	}

	events := ingest.snapshot()
	if len(events) != 2 {
		t.Fatalf("expected 2 ingest events (TOOL_CALL + POLICY_CHECK), got %d", len(events))
	}
	if events[0].EventType != EventToolCall {
		t.Errorf("first = %q, want TOOL_CALL", events[0].EventType)
	}
	if events[1].EventType != EventPolicyCheck {
		t.Errorf("second = %q, want POLICY_CHECK", events[1].EventType)
	}
	// Shared trace_id (spec §2.5 narrative).
	if events[0].TraceID != events[1].TraceID {
		t.Errorf("TOOL_CALL and POLICY_CHECK should share trace_id; got %v vs %v",
			events[0].TraceID, events[1].TraceID)
	}
	if events[1].Payload["result"] != "FAIL" {
		t.Errorf("POLICY_CHECK.result = %v, want FAIL", events[1].Payload["result"])
	}
	if events[1].Payload["reason"] != "PII" {
		t.Errorf("POLICY_CHECK.reason = %v, want PII", events[1].Payload["reason"])
	}
}
