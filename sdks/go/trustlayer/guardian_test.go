package trustlayer

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func sampleEvent() AgentTraceEvent {
	return NewEvent("researcher-1", "S1", EventToolCall,
		WithPayload(map[string]any{"tool_name": "external_llm"}),
	)
}

func TestGuardianReturnsParsedVerdict(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
            "decision": "FAIL",
            "rule": "block_external_llm",
            "reason": "PII",
            "policy": "default"
        }`))
	}))
	defer srv.Close()

	g, _ := NewGuardian(GuardianOptions{Endpoint: srv.URL, PolicyName: "default"})
	defer g.Close()
	v, err := g.Check(context.Background(), sampleEvent())
	if err != nil {
		t.Fatalf("check: %v", err)
	}
	if v.Decision != DecisionFail {
		t.Errorf("decision = %q, want FAIL", v.Decision)
	}
	if v.Rule == nil || *v.Rule != "block_external_llm" {
		t.Errorf("rule = %v, want block_external_llm", v.Rule)
	}
	if v.Policy != "default" {
		t.Errorf("policy = %q, want default", v.Policy)
	}
}

func TestGuardianSendsPolicyNameInBody(t *testing.T) {
	var bodyOut []byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bodyOut, _ = io.ReadAll(r.Body)
		_, _ = w.Write([]byte(`{"decision":"PASS","policy":"default"}`))
	}))
	defer srv.Close()

	g, _ := NewGuardian(GuardianOptions{Endpoint: srv.URL, PolicyName: "default"})
	_, _ = g.Check(context.Background(), sampleEvent())

	var req map[string]any
	if err := json.Unmarshal(bodyOut, &req); err != nil {
		t.Fatalf("server saw unparseable body: %v", err)
	}
	if req["policy_name"] != "default" {
		t.Errorf("policy_name = %v, want default", req["policy_name"])
	}
	if req["event"] == nil {
		t.Error("body missing 'event' key")
	}
}

func TestGuardianCheckWithPolicyOverrides(t *testing.T) {
	var seenPolicy any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req map[string]any
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &req)
		seenPolicy = req["policy_name"]
		_, _ = w.Write([]byte(`{"decision":"PASS","policy":"ad-hoc"}`))
	}))
	defer srv.Close()

	g, _ := NewGuardian(GuardianOptions{Endpoint: srv.URL, PolicyName: "default"})
	_, _ = g.CheckWithPolicy(context.Background(), sampleEvent(), "ad-hoc")
	if seenPolicy != "ad-hoc" {
		t.Errorf("policy_name override = %v, want ad-hoc", seenPolicy)
	}
}

func TestGuardianFailOpenOnTransportError(t *testing.T) {
	// Closed-immediately server == connection refused.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	srv.Close()

	g, _ := NewGuardian(GuardianOptions{Endpoint: srv.URL})
	v, err := g.Check(context.Background(), sampleEvent())
	if err != nil {
		t.Fatalf("expected nil error on transport failure, got %v", err)
	}
	if v.Decision != DecisionPass {
		t.Errorf("fail-open decision = %q, want PASS", v.Decision)
	}
	if v.Policy != "fallback" {
		t.Errorf("fallback policy = %q, want fallback", v.Policy)
	}
}

func TestGuardianFailClosedOnTransportError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	srv.Close()

	failClosed := false
	g, _ := NewGuardian(GuardianOptions{Endpoint: srv.URL, FailOpen: &failClosed})
	v, _ := g.Check(context.Background(), sampleEvent())
	if v.Decision != DecisionFail {
		t.Errorf("fail-closed decision = %q, want FAIL", v.Decision)
	}
}

func TestGuardianRejectsUnknownDecision(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"decision":"MAYBE","policy":"x"}`))
	}))
	defer srv.Close()

	g, _ := NewGuardian(GuardianOptions{Endpoint: srv.URL})
	v, _ := g.Check(context.Background(), sampleEvent())
	if v.Decision != DecisionPass {
		t.Errorf("expected fail-open on unknown decision, got %q", v.Decision)
	}
	if v.Policy != "fallback" {
		t.Errorf("expected fallback policy on unknown decision, got %q", v.Policy)
	}
}

func TestGuardianAddsAuthHeader(t *testing.T) {
	var gotAuth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		_, _ = w.Write([]byte(`{"decision":"PASS","policy":"p"}`))
	}))
	defer srv.Close()

	g, _ := NewGuardian(GuardianOptions{Endpoint: srv.URL, APIKey: "secret"})
	_, _ = g.Check(context.Background(), sampleEvent())
	if gotAuth != "Bearer secret" {
		t.Errorf("Authorization = %q, want 'Bearer secret'", gotAuth)
	}
}

func TestGuardianFallsBackToEnvToken(t *testing.T) {
	t.Setenv(apiTokenEnvVar, "guard-env")
	var gotAuth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		_, _ = w.Write([]byte(`{"decision":"PASS","policy":"p"}`))
	}))
	defer srv.Close()

	g, _ := NewGuardian(GuardianOptions{Endpoint: srv.URL})
	_, _ = g.Check(context.Background(), sampleEvent())
	if gotAuth != "Bearer guard-env" {
		t.Errorf("Authorization = %q, want 'Bearer guard-env'", gotAuth)
	}
}

func TestGuardian5xxUsesFallback(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	g, _ := NewGuardian(GuardianOptions{Endpoint: srv.URL})
	v, _ := g.Check(context.Background(), sampleEvent())
	if v.Decision != DecisionPass {
		t.Errorf("expected fail-open PASS on 503, got %q", v.Decision)
	}
	if v.Reason == nil || !strings.Contains(*v.Reason, "HTTP 503") {
		t.Errorf("expected reason to mention HTTP 503, got %v", v.Reason)
	}
}
