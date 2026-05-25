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

func TestClientEmitsPostBodyAndAuthHeader(t *testing.T) {
	var gotAuth string
	var gotBody []byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		gotBody, _ = io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"stored":1}`))
	}))
	defer srv.Close()

	client, err := NewClient(ClientOptions{Endpoint: srv.URL, APIKey: "secret"})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()

	ev := NewEvent("a", "s", EventAgentStart)
	if err := client.Emit(context.Background(), ev); err != nil {
		t.Fatalf("emit: %v", err)
	}
	if gotAuth != "Bearer secret" {
		t.Errorf("Authorization = %q, want 'Bearer secret'", gotAuth)
	}
	var sentEvent AgentTraceEvent
	if err := json.Unmarshal(gotBody, &sentEvent); err != nil {
		t.Fatalf("server saw unparseable body: %v\n%s", err, gotBody)
	}
	if sentEvent.AgentID != "a" {
		t.Errorf("event sent with agent_id=%q", sentEvent.AgentID)
	}
}

func TestClientEmitBatchSendsArray(t *testing.T) {
	var gotBody []byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotBody, _ = io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	client, _ := NewClient(ClientOptions{Endpoint: srv.URL})
	batch := []AgentTraceEvent{
		NewEvent("a", "s", EventAgentStart),
		NewEvent("a", "s", EventAgentEnd),
	}
	if err := client.EmitBatch(context.Background(), batch); err != nil {
		t.Fatalf("emit batch: %v", err)
	}
	if !strings.HasPrefix(string(gotBody), "[") {
		t.Errorf("expected JSON array, got: %s", gotBody)
	}
	var got []AgentTraceEvent
	if err := json.Unmarshal(gotBody, &got); err != nil {
		t.Fatalf("server saw unparseable batch: %v", err)
	}
	if len(got) != 2 {
		t.Errorf("batch length = %d, want 2", len(got))
	}
}

func TestClientReturnsErrorOnHTTPFailure(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error":"boom"}`))
	}))
	defer srv.Close()

	client, _ := NewClient(ClientOptions{Endpoint: srv.URL})
	err := client.Emit(context.Background(), NewEvent("a", "s", EventAgentStart))
	if err == nil {
		t.Fatal("expected error on 500, got nil")
	}
	if !strings.Contains(err.Error(), "HTTP 500") {
		t.Errorf("expected HTTP 500 in error, got %v", err)
	}
}

func TestClientFallsBackToEnvToken(t *testing.T) {
	t.Setenv(apiTokenEnvVar, "from-env")
	var gotAuth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	client, _ := NewClient(ClientOptions{Endpoint: srv.URL}) // no APIKey
	_ = client.Emit(context.Background(), NewEvent("a", "s", EventAgentStart))
	if gotAuth != "Bearer from-env" {
		t.Errorf("Authorization = %q, want 'Bearer from-env'", gotAuth)
	}
}

func TestClientExplicitTokenOverridesEnv(t *testing.T) {
	t.Setenv(apiTokenEnvVar, "from-env")
	var gotAuth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	client, _ := NewClient(ClientOptions{Endpoint: srv.URL, APIKey: "explicit"})
	_ = client.Emit(context.Background(), NewEvent("a", "s", EventAgentStart))
	if gotAuth != "Bearer explicit" {
		t.Errorf("Authorization = %q, want 'Bearer explicit'", gotAuth)
	}
}

func TestClientOmitsAuthWhenUnset(t *testing.T) {
	t.Setenv(apiTokenEnvVar, "")
	var gotAuth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	client, _ := NewClient(ClientOptions{Endpoint: srv.URL})
	_ = client.Emit(context.Background(), NewEvent("a", "s", EventAgentStart))
	if gotAuth != "" {
		t.Errorf("Authorization = %q, want empty", gotAuth)
	}
}

func TestEmitBatchEmptyIsNoOp(t *testing.T) {
	hit := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hit = true
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	client, _ := NewClient(ClientOptions{Endpoint: srv.URL})
	if err := client.EmitBatch(context.Background(), nil); err != nil {
		t.Fatalf("nil batch: %v", err)
	}
	if err := client.EmitBatch(context.Background(), []AgentTraceEvent{}); err != nil {
		t.Fatalf("empty batch: %v", err)
	}
	if hit {
		t.Error("server should not have been called for empty batch")
	}
}
