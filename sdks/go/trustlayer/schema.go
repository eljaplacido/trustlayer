package trustlayer

import (
	"bytes"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
)

// SchemaVersion is the wire-format version this SDK targets.
// See spec/v0.1/README.md for the normative declaration.
const SchemaVersion = "0.1"

// EventType is the closed enum of event_type values. New values
// are introduced as wire-format MINOR bumps (spec §1.7).
type EventType string

const (
	EventAgentStart      EventType = "AGENT_START"
	EventToolCall        EventType = "TOOL_CALL"
	EventToolResult      EventType = "TOOL_RESULT"
	EventLLMCall         EventType = "LLM_CALL"
	EventPolicyCheck     EventType = "POLICY_CHECK"
	EventHumanEscalation EventType = "HUMAN_ESCALATION"
	EventAgentEnd        EventType = "AGENT_END"
)

var validEventTypes = map[EventType]struct{}{
	EventAgentStart:      {},
	EventToolCall:        {},
	EventToolResult:      {},
	EventLLMCall:         {},
	EventPolicyCheck:     {},
	EventHumanEscalation: {},
	EventAgentEnd:        {},
}

// UnmarshalJSON rejects unknown enum values to enforce W4 conformance.
func (e *EventType) UnmarshalJSON(data []byte) error {
	var s string
	if err := json.Unmarshal(data, &s); err != nil {
		return err
	}
	v := EventType(s)
	if _, ok := validEventTypes[v]; !ok {
		return fmt.Errorf("trustlayer: unknown event_type %q", s)
	}
	*e = v
	return nil
}

// CynefinDomain classifies the interaction context. Default is
// CynefinDisorder (spec §1.3 / §3.2).
type CynefinDomain string

const (
	CynefinClear       CynefinDomain = "CLEAR"
	CynefinComplicated CynefinDomain = "COMPLICATED"
	CynefinComplex     CynefinDomain = "COMPLEX"
	CynefinChaotic     CynefinDomain = "CHAOTIC"
	CynefinDisorder    CynefinDomain = "DISORDER"
)

var validCynefinDomains = map[CynefinDomain]struct{}{
	CynefinClear:       {},
	CynefinComplicated: {},
	CynefinComplex:     {},
	CynefinChaotic:     {},
	CynefinDisorder:    {},
}

func (d *CynefinDomain) UnmarshalJSON(data []byte) error {
	var s string
	if err := json.Unmarshal(data, &s); err != nil {
		return err
	}
	v := CynefinDomain(s)
	if _, ok := validCynefinDomains[v]; !ok {
		return fmt.Errorf("trustlayer: unknown cynefin_domain %q", s)
	}
	*d = v
	return nil
}

// Decision is the guardian's verdict domain. Shared with
// POLICY_CHECK.payload.result (spec §2.5, §5.2).
type Decision string

const (
	DecisionPass     Decision = "PASS"
	DecisionFail     Decision = "FAIL"
	DecisionEscalate Decision = "ESCALATE"
)

var validDecisions = map[Decision]struct{}{
	DecisionPass:     {},
	DecisionFail:     {},
	DecisionEscalate: {},
}

func (d *Decision) UnmarshalJSON(data []byte) error {
	var s string
	if err := json.Unmarshal(data, &s); err != nil {
		return err
	}
	v := Decision(s)
	if _, ok := validDecisions[v]; !ok {
		return fmt.Errorf("trustlayer: unknown decision %q", s)
	}
	*d = v
	return nil
}

// Metrics is the cost/latency envelope (spec §1.5). Unknown keys are
// preserved in Extra so round-trips don't drop them.
type Metrics struct {
	LatencyMs        *float64       `json:"latency_ms,omitempty"`
	CostUSD          *float64       `json:"cost_usd,omitempty"`
	TokensPrompt     *uint32        `json:"tokens_prompt,omitempty"`
	TokensCompletion *uint32        `json:"tokens_completion,omitempty"`
	Extra            map[string]any `json:"-"`
}

var knownMetricsKeys = map[string]struct{}{
	"latency_ms":        {},
	"cost_usd":          {},
	"tokens_prompt":     {},
	"tokens_completion": {},
}

// MarshalJSON flattens Extra alongside the well-known keys.
func (m Metrics) MarshalJSON() ([]byte, error) {
	out := make(map[string]any, len(m.Extra)+4)
	if m.LatencyMs != nil {
		out["latency_ms"] = *m.LatencyMs
	}
	if m.CostUSD != nil {
		out["cost_usd"] = *m.CostUSD
	}
	if m.TokensPrompt != nil {
		out["tokens_prompt"] = *m.TokensPrompt
	}
	if m.TokensCompletion != nil {
		out["tokens_completion"] = *m.TokensCompletion
	}
	for k, v := range m.Extra {
		if _, clash := knownMetricsKeys[k]; clash {
			// Well-known keys win; Extra holds only unknown extensions.
			continue
		}
		out[k] = v
	}
	return json.Marshal(out)
}

// UnmarshalJSON splits known keys into typed fields and stashes the rest
// in Extra. We intentionally do NOT call DisallowUnknownFields here —
// spec §1.5 allows additional metrics keys and they must round-trip.
func (m *Metrics) UnmarshalJSON(data []byte) error {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	*m = Metrics{Extra: make(map[string]any)}
	if v, ok := raw["latency_ms"]; ok {
		var x float64
		if err := json.Unmarshal(v, &x); err != nil {
			return fmt.Errorf("metrics.latency_ms: %w", err)
		}
		m.LatencyMs = &x
	}
	if v, ok := raw["cost_usd"]; ok {
		var x float64
		if err := json.Unmarshal(v, &x); err != nil {
			return fmt.Errorf("metrics.cost_usd: %w", err)
		}
		m.CostUSD = &x
	}
	if v, ok := raw["tokens_prompt"]; ok {
		var x uint32
		if err := json.Unmarshal(v, &x); err != nil {
			return fmt.Errorf("metrics.tokens_prompt: %w", err)
		}
		m.TokensPrompt = &x
	}
	if v, ok := raw["tokens_completion"]; ok {
		var x uint32
		if err := json.Unmarshal(v, &x); err != nil {
			return fmt.Errorf("metrics.tokens_completion: %w", err)
		}
		m.TokensCompletion = &x
	}
	for k, v := range raw {
		if _, known := knownMetricsKeys[k]; known {
			continue
		}
		var any_ any
		if err := json.Unmarshal(v, &any_); err != nil {
			return fmt.Errorf("metrics.%s: %w", k, err)
		}
		m.Extra[k] = any_
	}
	return nil
}

// AgentTraceEvent is the canonical envelope (spec §1).
type AgentTraceEvent struct {
	TraceID       uuid.UUID      `json:"trace_id"`
	AgentID       string         `json:"agent_id"`
	SessionID     string         `json:"session_id"`
	Timestamp     time.Time      `json:"timestamp"`
	EventType     EventType      `json:"event_type"`
	CynefinDomain CynefinDomain  `json:"cynefin_domain,omitempty"`
	Payload       map[string]any `json:"payload,omitempty"`
	Metrics       Metrics        `json:"metrics,omitempty"`
}

// NewEvent constructs a fresh event with a new trace_id and timestamp.
// agent_id, session_id, and event_type are required; pass options to
// fill the rest.
func NewEvent(agentID, sessionID string, eventType EventType, opts ...EventOption) AgentTraceEvent {
	e := AgentTraceEvent{
		TraceID:       uuid.New(),
		AgentID:       agentID,
		SessionID:     sessionID,
		Timestamp:     time.Now().UTC(),
		EventType:     eventType,
		CynefinDomain: CynefinDisorder,
		Payload:       map[string]any{},
	}
	for _, o := range opts {
		o(&e)
	}
	return e
}

// EventOption mutates an AgentTraceEvent at construction.
type EventOption func(*AgentTraceEvent)

// WithPayload sets the event payload.
func WithPayload(p map[string]any) EventOption {
	return func(e *AgentTraceEvent) {
		if p == nil {
			e.Payload = map[string]any{}
			return
		}
		e.Payload = p
	}
}

// WithCynefin overrides the default CynefinDisorder domain.
func WithCynefin(d CynefinDomain) EventOption {
	return func(e *AgentTraceEvent) { e.CynefinDomain = d }
}

// WithMetrics overrides the (empty) metrics envelope.
func WithMetrics(m Metrics) EventOption {
	return func(e *AgentTraceEvent) { e.Metrics = m }
}

// WithTimestamp overrides the default time.Now timestamp; mostly used
// in tests and deterministic replays.
func WithTimestamp(t time.Time) EventOption {
	return func(e *AgentTraceEvent) { e.Timestamp = t.UTC() }
}

// envelopeKeys is the closed set of top-level fields permitted on an
// AgentTraceEvent (spec §1.2). Any other top-level key is a wire error.
var envelopeKeys = map[string]struct{}{
	"trace_id":       {},
	"agent_id":       {},
	"session_id":     {},
	"timestamp":      {},
	"event_type":     {},
	"cynefin_domain": {},
	"payload":        {},
	"metrics":        {},
}

// UnmarshalJSON enforces the strict envelope (W1 conformance) before
// delegating to the auto-generated decode logic.
func (e *AgentTraceEvent) UnmarshalJSON(data []byte) error {
	var raw map[string]json.RawMessage
	dec := json.NewDecoder(bytes.NewReader(data))
	if err := dec.Decode(&raw); err != nil {
		return err
	}
	for k := range raw {
		if _, ok := envelopeKeys[k]; !ok {
			return fmt.Errorf("trustlayer: unknown envelope field %q", k)
		}
	}
	type alias AgentTraceEvent
	var a alias
	if err := json.Unmarshal(data, &a); err != nil {
		return err
	}
	if a.EventType == "" {
		return fmt.Errorf("trustlayer: event_type is required")
	}
	if a.AgentID == "" {
		return fmt.Errorf("trustlayer: agent_id is required")
	}
	if a.SessionID == "" {
		return fmt.Errorf("trustlayer: session_id is required")
	}
	if a.CynefinDomain == "" {
		a.CynefinDomain = CynefinDisorder
	}
	if a.Payload == nil {
		a.Payload = map[string]any{}
	}
	*e = AgentTraceEvent(a)
	return nil
}

// MarshalJSON formats timestamps with a UTC offset so the wire form
// matches the spec (and what Python and TypeScript emit).
func (e AgentTraceEvent) MarshalJSON() ([]byte, error) {
	type alias AgentTraceEvent
	// Force the offset form spec §1.3 mandates.
	clone := alias(e)
	clone.Timestamp = clone.Timestamp.UTC()
	if clone.CynefinDomain == "" {
		clone.CynefinDomain = CynefinDisorder
	}
	if clone.Payload == nil {
		clone.Payload = map[string]any{}
	}
	return json.Marshal(clone)
}
