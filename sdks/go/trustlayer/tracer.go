package trustlayer

import (
	"context"
	"time"
)

// Tracer is a goroutine-safe convenience wrapper that knows which
// (agent_id, session_id) it belongs to and ships events through a
// shared TrustLayerClient.
type Tracer struct {
	client    *TrustLayerClient
	agentID   string
	sessionID string
}

// NewTracer pairs a client with an (agent_id, session_id).
func NewTracer(client *TrustLayerClient, agentID, sessionID string) *Tracer {
	return &Tracer{
		client:    client,
		agentID:   agentID,
		sessionID: sessionID,
	}
}

// Emit ships a pre-built event. Convenience pass-through to the client.
func (t *Tracer) Emit(ctx context.Context, event AgentTraceEvent) error {
	return t.client.Emit(ctx, event)
}

// ToolCall opens a tool-call span. Returns a closer that emits a
// TOOL_RESULT event when invoked (typically via defer). The result and
// error pointers are read at closer time, so callers can write to them
// in the body of the spanned code:
//
//	var result any
//	var err error
//	close := tracer.ToolCall(ctx, "calc", map[string]any{"x": 1}, &result, &err)
//	defer close()
//	result, err = doTheCall()
//
// If result/err are nil they're treated as "no result" / "no error".
func (t *Tracer) ToolCall(ctx context.Context, name string, args map[string]any, result *any, errOut *error) func() {
	startEvent := NewEvent(t.agentID, t.sessionID, EventToolCall,
		WithPayload(map[string]any{
			"tool_name": name,
			"tool_args": args,
		}),
	)
	start := time.Now()
	_ = t.client.Emit(ctx, startEvent)
	return func() {
		latencyMs := float64(time.Since(start).Microseconds()) / 1000.0
		payload := map[string]any{"tool_name": name}
		if result != nil {
			payload["result"] = *result
		}
		if errOut != nil && *errOut != nil {
			payload["error"] = (*errOut).Error()
		}
		resultEvent := NewEvent(t.agentID, t.sessionID, EventToolResult,
			WithPayload(payload),
			WithMetrics(Metrics{LatencyMs: &latencyMs}),
		)
		_ = t.client.Emit(ctx, resultEvent)
	}
}

// TracerCheck configures one call to Tracer.Check.
type TracerCheck struct {
	// Guardian is required.
	Guardian *GuardianClient
	// PolicyName overrides the guardian's configured default for this call.
	PolicyName string
	// CynefinDomain on the emitted TOOL_CALL + POLICY_CHECK events.
	// Defaults to CynefinDisorder if zero.
	CynefinDomain CynefinDomain
}

// Check is the ergonomic helper: emit a TOOL_CALL, ask the guardian,
// emit a POLICY_CHECK carrying the verdict so the trace and the
// decision share a trace_id, and return the Verdict so the caller can
// decide whether to invoke the tool. Matches the Python / TypeScript
// Tracer.check() shape (Phase 4.5).
func (t *Tracer) Check(ctx context.Context, toolName string, toolArgs map[string]any, opts *TracerCheck) (Verdict, error) {
	if opts == nil || opts.Guardian == nil {
		return Verdict{}, errMissingGuardian
	}
	domain := opts.CynefinDomain
	if domain == "" {
		domain = CynefinDisorder
	}
	call := NewEvent(t.agentID, t.sessionID, EventToolCall,
		WithCynefin(domain),
		WithPayload(map[string]any{
			"tool_name": toolName,
			"tool_args": toolArgs,
		}),
	)
	_ = t.client.Emit(ctx, call)

	verdict, _ := opts.Guardian.CheckWithPolicy(ctx, call, opts.PolicyName)

	policyName := opts.PolicyName
	if policyName == "" {
		policyName = verdict.Policy
	}
	reason := ""
	if verdict.Reason != nil {
		reason = *verdict.Reason
	}
	policyCheck := NewEvent(t.agentID, t.sessionID, EventPolicyCheck,
		WithCynefin(domain),
		WithPayload(map[string]any{
			"policy_name": policyName,
			"action":      toolName,
			"result":      string(verdict.Decision),
			"reason":      reason,
		}),
	)
	// Share trace_id with the originating tool call so the trace stream
	// can correlate the verdict with the action.
	policyCheck.TraceID = call.TraceID
	_ = t.client.Emit(ctx, policyCheck)
	return verdict, nil
}

// errMissingGuardian is returned when Tracer.Check is called without a
// Guardian wired up in TracerCheck.
var errMissingGuardian = &tracerError{msg: "trustlayer: Tracer.Check requires opts.Guardian"}

type tracerError struct{ msg string }

func (e *tracerError) Error() string { return e.msg }
