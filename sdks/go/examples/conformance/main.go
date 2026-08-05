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
