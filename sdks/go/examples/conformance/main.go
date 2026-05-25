// Conformance fixture generator (ADR-010 follow-up).
//
// Produces deterministic, canonical AgentTraceEvent JSON that the
// cross-language test in core-rs/tests/cross_language.rs ingests to
// prove the Go SDK round-trips through the same envelope as the
// Python + TypeScript SDKs.
//
// Run:
//
//	cd sdks/go && go run ./examples/conformance > ../../spec/v0.1/fixtures/event-canonical-go.json
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/eljaplacido/trustlayer/sdks/go/trustlayer"
	"github.com/google/uuid"
)

func main() {
	// Deterministic values so the fixture is byte-stable across runs.
	traceID := uuid.MustParse("33333333-3333-4333-8333-333333333333")
	ts, _ := time.Parse(time.RFC3339, "2026-05-25T09:00:00+00:00")

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
		trustlayer.WithTimestamp(ts),
	)
	ev.TraceID = traceID

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

	out, err := json.MarshalIndent(ev, "", "  ")
	if err != nil {
		fmt.Fprintln(os.Stderr, "encode:", err)
		os.Exit(1)
	}
	fmt.Println(string(out))
}
