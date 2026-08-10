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
//	go run ./examples/conformance tool-result      > ../../spec/v0.1/fixtures/event-tool-result-go.json
//	go run ./examples/conformance llm-call         > ../../spec/v0.1/fixtures/event-llm-call-go.json
//	go run ./examples/conformance policy-check     > ../../spec/v0.1/fixtures/event-policy-check-go.json
//	go run ./examples/conformance human-escalation > ../../spec/v0.1/fixtures/event-human-escalation-go.json
//	go run ./examples/conformance agent-end        > ../../spec/v0.1/fixtures/event-agent-end-go.json
//	go run ./examples/conformance disclosure-shown > ../../spec/v0.1/fixtures/event-disclosure-shown-go.json
//	go run ./examples/conformance content-marked   > ../../spec/v0.1/fixtures/event-content-marked-go.json
//	go run ./examples/conformance human-decision   > ../../spec/v0.1/fixtures/event-human-decision-go.json
//	go run ./examples/conformance harness-snapshot > ../../spec/v0.1/fixtures/event-harness-snapshot-go.json
//	go run ./examples/conformance delegated        > ../../spec/v0.1/fixtures/event-delegated-go.json
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
	"tool-result":      toolResult,
	"llm-call":         llmCall,
	"policy-check":     policyCheck,
	"human-escalation": humanEscalation,
	"agent-end":        agentEnd,
	"disclosure-shown": disclosureShown,
	"content-marked":   contentMarked,
	"human-decision":   humanDecision,
	"harness-snapshot": harnessSnapshot,
	"delegated":        delegatedAgentStart,
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

// toolResult closes the canonical TOOL_CALL above (spec §2.3). Same agent and
// session, so the pair reads as one tool invocation rather than two unrelated
// events. `error` is null on the success path — present, not omitted, because
// a receiver distinguishing "no error" from "field absent" is the behaviour
// W1 strict parsing exists to pin down.
func toolResult() trustlayer.AgentTraceEvent {
	latency := 812.0
	ev := trustlayer.NewEvent(
		"researcher-1",
		"S1",
		trustlayer.EventToolResult,
		trustlayer.WithCynefin(trustlayer.CynefinComplex),
		trustlayer.WithPayload(map[string]any{
			"tool_name": "external_llm",
			"result":    map[string]any{"summary": "Three findings, none blocking."},
			"error":     nil,
		}),
		trustlayer.WithMetrics(trustlayer.Metrics{LatencyMs: &latency}),
		trustlayer.WithTimestamp(mustTime("2026-05-25T09:00:01+00:00")),
	)
	ev.TraceID = uuid.MustParse("44444444-4444-4444-8444-444444444444")
	return ev
}

// llmCall pins a model invocation the agent drives itself (spec §2.4). The
// prompt and response are deliberately short and synthetic: this file is
// committed to a public repository, and §2.4 marks both fields
// privacy-sensitive.
func llmCall() trustlayer.AgentTraceEvent {
	latency := 640.0
	cost := 0.0021
	prompt := uint32(210)
	completion := uint32(88)
	ev := trustlayer.NewEvent(
		"researcher-1",
		"S1",
		trustlayer.EventLLMCall,
		trustlayer.WithCynefin(trustlayer.CynefinComplicated),
		trustlayer.WithPayload(map[string]any{
			"model":    "claude-opus-5",
			"prompt":   "Summarise the attached report in three bullets.",
			"response": "1. Costs fell. 2. Latency held. 3. No policy failures.",
		}),
		trustlayer.WithMetrics(trustlayer.Metrics{
			LatencyMs:        &latency,
			CostUSD:          &cost,
			TokensPrompt:     &prompt,
			TokensCompletion: &completion,
		}),
		trustlayer.WithTimestamp(mustTime("2026-05-25T09:00:02+00:00")),
	)
	ev.TraceID = uuid.MustParse("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
	return ev
}

// policyCheck pins the FAIL branch (spec §2.5) rather than a PASS. A fixture
// that only ever carries PASS would let a receiver that drops `reason`
// entirely still look conformant, because PASS is exactly the case where
// `reason` is null. The values match what `policies/default.json` actually
// returns for this tool.
func policyCheck() trustlayer.AgentTraceEvent {
	ev := trustlayer.NewEvent(
		"researcher-1",
		"S1",
		trustlayer.EventPolicyCheck,
		trustlayer.WithCynefin(trustlayer.CynefinComplex),
		trustlayer.WithPayload(map[string]any{
			"policy_name": "default",
			"action":      "external_llm",
			"result":      "FAIL",
			"reason":      "External LLM is disabled in this policy. Use the in-house model.",
		}),
		trustlayer.WithTimestamp(mustTime("2026-05-25T09:00:03+00:00")),
	)
	ev.TraceID = uuid.MustParse("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
	return ev
}

// humanEscalation is the event `humanDecision` resolves — its trace_id is the
// `escalation_trace_id` that fixture carries (spec §2.6). Kept as a matched
// pair on purpose: Art. 14 effectiveness is measured on the gap between the
// two, so a fixture set with a decision and no escalation cannot exercise it.
func humanEscalation() trustlayer.AgentTraceEvent {
	ev := trustlayer.NewEvent(
		"art14-agent",
		"S14",
		trustlayer.EventHumanEscalation,
		trustlayer.WithCynefin(trustlayer.CynefinComplicated),
		trustlayer.WithPayload(map[string]any{
			"reason": "Payment exceeds the agent's delegated authority.",
			"context": map[string]any{
				"amount_eur": 4800,
				"vendor":     "vendor-2b91",
				"tool_name":  "payments.transfer",
			},
		}),
		trustlayer.WithTimestamp(mustTime("2026-08-07T10:01:18+00:00")),
	)
	ev.TraceID = uuid.MustParse("77777777-7777-4777-8777-777777777777")
	return ev
}

// agentEnd closes the researcher-1 session (spec §2.7).
func agentEnd() trustlayer.AgentTraceEvent {
	ev := trustlayer.NewEvent(
		"researcher-1",
		"S1",
		trustlayer.EventAgentEnd,
		trustlayer.WithCynefin(trustlayer.CynefinClear),
		trustlayer.WithPayload(map[string]any{
			"status":  "completed",
			"summary": "Report summarised; one tool call blocked by policy.",
		}),
		trustlayer.WithTimestamp(mustTime("2026-05-25T09:00:04+00:00")),
	)
	ev.TraceID = uuid.MustParse("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
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

// delegatedAgentStart exercises parent_trace_id (spec 1.3): a sub-agent's
// AGENT_START carrying the trace_id of the TOOL_CALL that spawned it. That
// single convention is what makes cross-agent delegation depth computable.
func delegatedAgentStart() trustlayer.AgentTraceEvent {
	parent := uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
	ev := trustlayer.NewEvent(
		"sub-agent",
		"S43",
		trustlayer.EventAgentStart,
		trustlayer.WithCynefin(trustlayer.CynefinComplex),
		trustlayer.WithPayload(map[string]any{
			"goal": "Summarise the fetched document",
		}),
		trustlayer.WithTimestamp(mustTime("2026-08-07T10:00:05+00:00")),
	)
	ev.TraceID = uuid.MustParse("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
	ev.ParentTraceID = &parent
	return ev
}
