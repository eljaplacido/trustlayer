// Conformance fixture generator (ADR-010 follow-up).
//
// Produces deterministic, canonical AgentTraceEvent JSON that the
// cross-language test in core-rs/tests/cross_language.rs ingests to
// prove the Go SDK round-trips through the same envelope as the
// Python + TypeScript SDKs.
//
// Each fixture is selected by name so the output stays a single event on
// stdout, matching the procedure in spec/v0.1/fixtures/README.md.
//
// Run:
//
//	cd sdks/go
//	go run ./examples/conformance canonical        > ../../spec/v0.1/fixtures/event-canonical-go.json
//	go run ./examples/conformance disclosure-shown > ../../spec/v0.1/fixtures/event-disclosure-shown-go.json
//	go run ./examples/conformance content-marked   > ../../spec/v0.1/fixtures/event-content-marked-go.json
//	go run ./examples/conformance human-decision   > ../../spec/v0.1/fixtures/event-human-decision-go.json
//	go run ./examples/conformance harness-snapshot > ../../spec/v0.1/fixtures/event-harness-snapshot-go.json
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"time"

	"github.com/eljaplacido/trustlayer/sdks/go/trustlayer"
	"github.com/google/uuid"
)

// fixtures maps a CLI name to a builder. Every value is pinned so
// successive runs are byte-identical (spec/v0.1/fixtures/README.md).
var fixtures = map[string]func() trustlayer.AgentTraceEvent{
	"canonical":        canonicalToolCall,
	"disclosure-shown": disclosureShown,
	"content-marked":   contentMarked,
	"human-decision":   humanDecision,
	"harness-snapshot": harnessSnapshot,
}

func main() {
	name := "canonical"
	if len(os.Args) > 1 {
		name = os.Args[1]
	}

	build, ok := fixtures[name]
	if !ok {
		names := make([]string, 0, len(fixtures))
		for k := range fixtures {
			names = append(names, k)
		}
		sort.Strings(names)
		fmt.Fprintf(os.Stderr, "unknown fixture %q; want one of %v\n", name, names)
		os.Exit(2)
	}

	out, err := json.MarshalIndent(build(), "", "  ")
	if err != nil {
		fmt.Fprintln(os.Stderr, "encode:", err)
		os.Exit(1)
	}
	fmt.Println(string(out))
}

func mustTime(value string) time.Time {
	ts, err := time.Parse(time.RFC3339, value)
	if err != nil {
		fmt.Fprintln(os.Stderr, "parse timestamp:", err)
		os.Exit(1)
	}
	return ts
}

func canonicalToolCall() trustlayer.AgentTraceEvent {
	ev := trustlayer.NewEvent(
		"researcher-1",
		"S1",
		trustlayer.EventToolCall,
		trustlayer.WithCynefin(trustlayer.CynefinComplex),
		trustlayer.WithPayload(map[string]any{
			"tool_name": "external_llm",
			"tool_args": map[string]any{"prompt": "hi"},
			"model":     "gpt-4",
		}),
		trustlayer.WithTimestamp(mustTime("2026-05-25T09:00:00+00:00")),
	)
	ev.TraceID = uuid.MustParse("33333333-3333-4333-8333-333333333333")

	latency := 12.5
	cost := 0.0015
	prompt := uint32(150)
	completion := uint32(45)
	ev.Metrics = trustlayer.Metrics{
		LatencyMs:        &latency,
		CostUSD:          &cost,
		TokensPrompt:     &prompt,
		TokensCompletion: &completion,
	}
	return ev
}

// disclosureShown pins an EU AI Act Art. 50(1) interaction disclosure
// (spec/v0.1/02-event-types.md §2.8).
func disclosureShown() trustlayer.AgentTraceEvent {
	ev := trustlayer.NewEvent(
		"art50-agent",
		"S50",
		trustlayer.EventDisclosureShown,
		trustlayer.WithCynefin(trustlayer.CynefinClear),
		trustlayer.WithPayload(map[string]any{
			"disclosure_type": "ai_interaction",
			"user_notice":     "You are interacting with an AI system.",
			"surface":         "chat_header",
			"locale":          "en-GB",
		}),
		trustlayer.WithTimestamp(mustTime("2026-07-03T10:00:00+00:00")),
	)
	ev.TraceID = uuid.MustParse("55555555-5555-4555-8555-555555555555")
	return ev
}

// contentMarked pins an Art. 50(2) marking carrying a verification block —
// the shape that can lift a control to VERIFIED rather than stopping at
// EVIDENCED (spec §2.9, ADR-019 §6).
func contentMarked() trustlayer.AgentTraceEvent {
	ev := trustlayer.NewEvent(
		"art50-agent",
		"S51",
		trustlayer.EventContentMarked,
		trustlayer.WithCynefin(trustlayer.CynefinClear),
		trustlayer.WithPayload(map[string]any{
			"marking_type":  "c2pa",
			"content_type":  "image",
			"artifact_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
			"confidence":    0.97,
			"verification": map[string]any{
				"method":      "c2pa",
				"verified":    true,
				"verified_at": "2026-07-03T10:01:00+00:00",
				"verifier":    "trustlayer-marking-verify/0.1",
			},
		}),
		trustlayer.WithTimestamp(mustTime("2026-07-03T10:01:00+00:00")),
	)
	ev.TraceID = uuid.MustParse("66666666-6666-4666-8666-666666666666")
	return ev
}

// humanDecision closes the Art. 14 loop: the *outcome* of an escalation
// (spec 2.10). Pinned latency because the escalation-to-decision gap is the
// number Art. 14 effectiveness is actually measured on.
func humanDecision() trustlayer.AgentTraceEvent {
	decisionLatency := 41200.0
	ev := trustlayer.NewEvent(
		"art14-agent",
		"S14",
		trustlayer.EventHumanDecision,
		trustlayer.WithCynefin(trustlayer.CynefinComplicated),
		trustlayer.WithPayload(map[string]any{
			"escalation_trace_id": "77777777-7777-4777-8777-777777777777",
			"decision":            "APPROVE",
			// Pseudonymous by design: Art. 14(4) needs an identified natural
			// person, not a name in a log that ships to third parties.
			"reviewer_id": "reviewer-7f3a",
			"rationale":   "Amount within delegated authority; vendor previously verified.",
		}),
		trustlayer.WithMetrics(trustlayer.Metrics{LatencyMs: &decisionLatency}),
		trustlayer.WithTimestamp(mustTime("2026-08-07T10:02:00+00:00")),
	)
	ev.TraceID = uuid.MustParse("88888888-8888-4888-8888-888888888888")
	return ev
}

// harnessSnapshot fingerprints the configuration a session ran under
// (spec 2.11). Note prompt *hashes* only — a system prompt is a trade secret
// and often carries customer data, and change detection only needs to know
// that it changed.
func harnessSnapshot() trustlayer.AgentTraceEvent {
	ev := trustlayer.NewEvent(
		"art43-agent",
		"S43",
		trustlayer.EventHarnessSnapshot,
		trustlayer.WithCynefin(trustlayer.CynefinClear),
		trustlayer.WithPayload(map[string]any{
			"harness_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
			"model_bindings": []any{
				map[string]any{
					"role":        "planner",
					"model":       "claude-opus-5",
					"provider":    "anthropic",
					"params_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
				},
			},
			"tools": []any{
				map[string]any{
					"name":         "payments.transfer",
					"version":      "1.4.0",
					"trust_tier":   "privileged",
					"capabilities": []any{"payments"},
				},
				map[string]any{
					"name":         "web.fetch",
					"version":      "0.9.1",
					"trust_tier":   "untrusted",
					"capabilities": []any{"net.egress"},
				},
			},
			"mcp_servers": []any{
				map[string]any{"name": "gitnexus", "version": "1.0.0", "transport": "stdio"},
			},
			"prompt_hashes": map[string]any{
				"system": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
			},
			"autonomy": map[string]any{
				"max_delegation_depth": 3,
				"human_in_loop":        true,
			},
			"sdk": map[string]any{"name": "trustlayer-go", "version": "0.1.0"},
		}),
		trustlayer.WithTimestamp(mustTime("2026-08-07T10:00:00+00:00")),
	)
	ev.TraceID = uuid.MustParse("99999999-9999-4999-8999-999999999999")
	return ev
}
