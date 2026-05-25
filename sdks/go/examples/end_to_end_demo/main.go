// End-to-end demo for the Go SDK.
//
// Boots two in-process HTTP servers:
//
//   - a fake guardian that returns a hard-coded verdict based on the
//     tool name (mirrors the Phase 4 cynepic-guardian contract),
//   - a fake ingest endpoint that prints each AgentTraceEvent it
//     receives to stdout.
//
// Then drives a Tracer through three calls — PASS / FAIL /
// ESCALATE-by-Cynefin-default — so a reader can see what the trace
// stream + guardian round-trip look like end to end without standing
// up the real Rust sidecar.
//
// Run:
//
//	cd sdks/go && go run ./examples/end_to_end_demo
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"

	"github.com/eljaplacido/trustlayer/sdks/go/trustlayer"
)

func main() {
	guardianSrv := httptest.NewServer(http.HandlerFunc(fakeGuardian))
	defer guardianSrv.Close()

	ingestSrv := httptest.NewServer(http.HandlerFunc(fakeIngest))
	defer ingestSrv.Close()

	client, _ := trustlayer.NewClient(trustlayer.ClientOptions{Endpoint: ingestSrv.URL})
	defer client.Close()

	guardian, _ := trustlayer.NewGuardian(trustlayer.GuardianOptions{
		Endpoint:   guardianSrv.URL,
		PolicyName: "default",
	})
	defer guardian.Close()

	tracer := trustlayer.NewTracer(client, "researcher-1", "S1")

	ctx := context.Background()

	scenarios := []struct {
		Tool   string
		Args   map[string]any
		Domain trustlayer.CynefinDomain
	}{
		{Tool: "calculator", Args: map[string]any{"x": 1}, Domain: trustlayer.CynefinClear},
		{Tool: "external_llm", Args: map[string]any{"prompt": "redact me"}, Domain: trustlayer.CynefinComplex},
		{Tool: "unknown_tool", Args: nil, Domain: trustlayer.CynefinChaotic},
	}

	for _, sc := range scenarios {
		fmt.Printf("\n--- %s [%s] ---\n", sc.Tool, sc.Domain)
		v, err := tracer.Check(ctx, sc.Tool, sc.Args, &trustlayer.TracerCheck{
			Guardian:      guardian,
			PolicyName:    "default",
			CynefinDomain: sc.Domain,
		})
		if err != nil {
			fmt.Println("error:", err)
			continue
		}
		reason := ""
		if v.Reason != nil {
			reason = *v.Reason
		}
		rule := ""
		if v.Rule != nil {
			rule = *v.Rule
		}
		fmt.Printf("verdict: %s (rule=%q, reason=%q, policy=%s)\n",
			v.Decision, rule, reason, v.Policy)
	}
}

// fakeGuardian: external_llm -> FAIL, calculator -> PASS, anything else
// inherits the Cynefin default the *real* guardian would compute. We
// imitate it here for demo purposes; in production the Rust sidecar
// would do this itself.
func fakeGuardian(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Event trustlayer.AgentTraceEvent `json:"event"`
	}
	body, _ := io.ReadAll(r.Body)
	if err := json.Unmarshal(body, &req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	tool, _ := req.Event.Payload["tool_name"].(string)
	reason := "n/a"
	out := map[string]any{"policy": "default"}
	switch {
	case tool == "calculator":
		out["decision"] = "PASS"
		out["rule"] = "allow_calculator"
		out["reason"] = nil
	case tool == "external_llm":
		out["decision"] = "FAIL"
		out["rule"] = "block_external_llm"
		out["reason"] = "PII concern"
	case req.Event.CynefinDomain == trustlayer.CynefinChaotic:
		out["decision"] = "ESCALATE"
		out["rule"] = nil
		out["reason"] = "CHAOTIC domain - no rule matched; escalating by default"
	default:
		out["decision"] = "PASS"
		out["rule"] = nil
		out["reason"] = nil
		_ = reason
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(out)
}

// fakeIngest: print every event to stdout so the demo is readable.
func fakeIngest(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	// Could be a single event or a batch — try both.
	var single trustlayer.AgentTraceEvent
	if err := json.Unmarshal(body, &single); err == nil && single.EventType != "" {
		out, _ := json.MarshalIndent(single, "  ", "  ")
		fmt.Println("  emit:", string(out))
		w.WriteHeader(http.StatusOK)
		return
	}
	var batch []trustlayer.AgentTraceEvent
	if err := json.Unmarshal(body, &batch); err == nil {
		for _, ev := range batch {
			out, _ := json.MarshalIndent(ev, "  ", "  ")
			fmt.Println("  emit:", string(out))
		}
	}
	w.WriteHeader(http.StatusOK)
}
