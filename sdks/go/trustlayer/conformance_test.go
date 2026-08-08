// Every v0.1 conformance fixture MUST parse under this SDK's strict envelope.
//
// spec/v0.1/fixtures/ holds deterministic artifacts that every conforming
// implementation has to accept (spec §6.2). The reference Rust core globs the
// directory from core-rs/tests/cross_language.rs; Phase 8's engineering
// contract (docs/PHASE-8-DESIGN.md §5.3) extends that rule to all four SDKs.
//
// This SDK also *produces* the fixtures via examples/conformance, which makes
// the round-trip below the check that matters most here: what the generator
// emits must survive this package's own strict decoder unchanged. A producer
// that cannot re-read its own output is not evidence of anything.
//
// Globbing rather than naming files means a fixture added to the spec is
// covered the moment it is committed.
package trustlayer

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// fixtureDir resolves spec/v0.1/fixtures relative to this package.
func fixtureDir(t *testing.T) string {
	t.Helper()
	return filepath.Join("..", "..", "..", "spec", "v0.1", "fixtures")
}

func fixturePaths(t *testing.T) []string {
	t.Helper()

	paths, err := filepath.Glob(filepath.Join(fixtureDir(t), "event-*.json"))
	if err != nil {
		t.Fatalf("globbing fixtures: %v", err)
	}
	// Guard the glob itself — a bad path would silently skip every subtest.
	if len(paths) == 0 {
		t.Fatalf("no event fixtures found under %s", fixtureDir(t))
	}
	return paths
}

func TestFixturesParseUnderStrictEnvelope(t *testing.T) {
	for _, path := range fixturePaths(t) {
		t.Run(filepath.Base(path), func(t *testing.T) {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("reading fixture: %v", err)
			}

			var event AgentTraceEvent
			if err := json.Unmarshal(raw, &event); err != nil {
				t.Fatalf("fixture does not parse: %v", err)
			}

			if event.AgentID == "" {
				t.Error("agent_id is required by spec §1.2")
			}
			if event.SessionID == "" {
				t.Error("session_id is required by spec §1.2")
			}
		})
	}
}

func TestFixturesRoundTripToAFixedPoint(t *testing.T) {
	for _, path := range fixturePaths(t) {
		t.Run(filepath.Base(path), func(t *testing.T) {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("reading fixture: %v", err)
			}

			var once AgentTraceEvent
			if err := json.Unmarshal(raw, &once); err != nil {
				t.Fatalf("first parse: %v", err)
			}

			encoded, err := json.Marshal(once)
			if err != nil {
				t.Fatalf("re-encoding: %v", err)
			}

			var twice AgentTraceEvent
			if err := json.Unmarshal(encoded, &twice); err != nil {
				t.Fatalf("second parse: %v", err)
			}

			reEncoded, err := json.Marshal(twice)
			if err != nil {
				t.Fatalf("re-encoding twice: %v", err)
			}

			if string(encoded) != string(reEncoded) {
				t.Errorf("round trip is not stable:\n first: %s\nsecond: %s", encoded, reEncoded)
			}
		})
	}
}

func TestFixturesPreserveEnvelopeFields(t *testing.T) {
	for _, path := range fixturePaths(t) {
		t.Run(filepath.Base(path), func(t *testing.T) {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("reading fixture: %v", err)
			}

			var asMap map[string]any
			if err := json.Unmarshal(raw, &asMap); err != nil {
				t.Fatalf("parsing fixture as a map: %v", err)
			}

			var event AgentTraceEvent
			if err := json.Unmarshal(raw, &event); err != nil {
				t.Fatalf("parsing fixture: %v", err)
			}

			if got, want := event.TraceID.String(), asMap["trace_id"]; got != want {
				t.Errorf("trace_id: got %q, want %q", got, want)
			}
			if got, want := event.AgentID, asMap["agent_id"]; got != want {
				t.Errorf("agent_id: got %q, want %q", got, want)
			}
			if got, want := event.SessionID, asMap["session_id"]; got != want {
				t.Errorf("session_id: got %q, want %q", got, want)
			}
			if got, want := string(event.EventType), asMap["event_type"]; got != want {
				t.Errorf("event_type: got %q, want %q", got, want)
			}
			if got, want := string(event.CynefinDomain), asMap["cynefin_domain"]; got != want {
				t.Errorf("cynefin_domain: got %q, want %q", got, want)
			}
		})
	}
}

func TestFixturesRejectUnknownEnvelopeField(t *testing.T) {
	// W1 strictness (spec §6.2). The positive cases above pass just as well
	// under a lenient decoder, so without this the suite would not actually
	// prove strictness.
	for _, path := range fixturePaths(t) {
		t.Run(filepath.Base(path), func(t *testing.T) {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("reading fixture: %v", err)
			}

			var asMap map[string]any
			if err := json.Unmarshal(raw, &asMap); err != nil {
				t.Fatalf("parsing fixture as a map: %v", err)
			}
			asMap["definitely_not_in_v0_1"] = true

			mutated, err := json.Marshal(asMap)
			if err != nil {
				t.Fatalf("re-encoding mutated fixture: %v", err)
			}

			var event AgentTraceEvent
			if err := json.Unmarshal(mutated, &event); err == nil {
				t.Error("unknown envelope field was accepted; W1 strictness is not enforced")
			}
		})
	}
}

// TestParentTraceIDIsOmittedWhenUnset guards the additive property of the
// field (spec §1.3). If it serialised as null when unset, every emitter that
// never sets it would start changing the bytes of a shipped format — and the
// byte-identical fixture guarantee the conformance suite rests on would break.
func TestParentTraceIDIsOmittedWhenUnset(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(fixtureDir(t), "event-canonical-go.json"))
	if err != nil {
		t.Fatalf("reading fixture: %v", err)
	}

	var event AgentTraceEvent
	if err := json.Unmarshal(raw, &event); err != nil {
		t.Fatalf("parsing: %v", err)
	}
	if event.ParentTraceID != nil {
		t.Errorf("v0.1 fixture must parse with no parent: %v", event.ParentTraceID)
	}

	encoded, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("encoding: %v", err)
	}
	if bytes.Contains(encoded, []byte("parent_trace_id")) {
		t.Errorf("unset parent_trace_id must not be serialised: %s", encoded)
	}
}

func TestParentTraceIDRoundTripsWhenPresent(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(fixtureDir(t), "event-delegated-go.json"))
	if err != nil {
		t.Fatalf("reading fixture: %v", err)
	}

	var event AgentTraceEvent
	if err := json.Unmarshal(raw, &event); err != nil {
		t.Fatalf("parsing: %v", err)
	}
	if event.ParentTraceID == nil {
		t.Fatal("parent_trace_id must survive the round trip")
	}
	if got := event.ParentTraceID.String(); got != "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" {
		t.Errorf("parent_trace_id: got %q", got)
	}
}
