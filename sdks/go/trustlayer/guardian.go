package trustlayer

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// DefaultGuardianEndpoint is the loopback URL the reference Rust
// sidecar serves /v1/check on. Override via GuardianOptions.Endpoint.
const DefaultGuardianEndpoint = "http://127.0.0.1:8089/v1/check"

// GuardianOptions configures the cynepic-guardian client.
type GuardianOptions struct {
	// Endpoint is the full URL to POST /v1/check on. Empty = default.
	Endpoint string
	// PolicyName picks a named policy on the server. Empty = server default.
	PolicyName string
	// APIKey is the bearer token (ADR-007). Same resolution order as
	// the ingest client.
	APIKey string
	// HTTPClient lets callers inject a *http.Client. nil installs a
	// fresh client with a 1s timeout (matches the Python default —
	// guardian calls are on the hot path).
	HTTPClient *http.Client
	// FailOpen controls the fallback verdict when the guardian is
	// unreachable. true (default) returns PASS so a guardian outage
	// doesn't take down the host agent.
	FailOpen *bool
}

// Verdict is the guardian's reply (spec §5.2).
type Verdict struct {
	Decision Decision `json:"decision"`
	Rule     *string  `json:"rule,omitempty"`
	Reason   *string  `json:"reason,omitempty"`
	Policy   string   `json:"policy"`
}

// GuardianClient is a goroutine-safe guardian client.
type GuardianClient struct {
	endpoint   string
	policyName string
	apiKey     string
	http       *http.Client
	failOpen   bool
}

// NewGuardian constructs a GuardianClient. Like NewClient, no I/O until
// the first Check.
func NewGuardian(opts GuardianOptions) (*GuardianClient, error) {
	endpoint := opts.Endpoint
	if endpoint == "" {
		endpoint = DefaultGuardianEndpoint
	}
	httpClient := opts.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: time.Second}
	}
	failOpen := true
	if opts.FailOpen != nil {
		failOpen = *opts.FailOpen
	}
	return &GuardianClient{
		endpoint:   endpoint,
		policyName: opts.PolicyName,
		apiKey:     resolveAPIToken(opts.APIKey),
		http:       httpClient,
		failOpen:   failOpen,
	}, nil
}

// Endpoint exposes the configured URL (handy for tests).
func (g *GuardianClient) Endpoint() string { return g.endpoint }

// FailOpen reports the configured fallback posture.
func (g *GuardianClient) FailOpen() bool { return g.failOpen }

// Check forwards an event to the guardian and returns the verdict.
// On any transport / parse failure, returns a synthetic
// {Policy: "fallback"} verdict whose Decision depends on FailOpen.
// The error return is always nil — instrumentation must never propagate
// guardian failures as fatal — but the synthetic verdict's Reason
// carries the detail for logging.
func (g *GuardianClient) Check(ctx context.Context, event AgentTraceEvent) (Verdict, error) {
	body, err := json.Marshal(map[string]any{
		"event":       event,
		"policy_name": policyNameJSON(g.policyName),
	})
	if err != nil {
		return g.fallback(fmt.Sprintf("marshal request: %s", err)), nil
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, g.endpoint, bytes.NewReader(body))
	if err != nil {
		return g.fallback(fmt.Sprintf("build request: %s", err)), nil
	}
	req.Header.Set("Content-Type", "application/json")
	if g.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+g.apiKey)
	}
	resp, err := g.http.Do(req)
	if err != nil {
		return g.fallback(fmt.Sprintf("transport: %s", err)), nil
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return g.fallback(fmt.Sprintf("HTTP %d", resp.StatusCode)), nil
	}
	var v Verdict
	if err := json.NewDecoder(resp.Body).Decode(&v); err != nil {
		return g.fallback(fmt.Sprintf("decode verdict: %s", err)), nil
	}
	if _, ok := validDecisions[v.Decision]; !ok {
		return g.fallback(fmt.Sprintf("unexpected decision %q", v.Decision)), nil
	}
	if v.Policy == "" {
		v.Policy = "unknown"
	}
	return v, nil
}

// CheckWithPolicy overrides the configured policy_name for one call.
func (g *GuardianClient) CheckWithPolicy(ctx context.Context, event AgentTraceEvent, policyName string) (Verdict, error) {
	g2 := *g
	g2.policyName = policyName
	return g2.Check(ctx, event)
}

// policyNameJSON returns an interface that marshals to null when the
// configured policy_name is empty, so the wire request matches the
// shape sent by the Python and TypeScript SDKs.
func policyNameJSON(name string) any {
	if name == "" {
		return nil
	}
	return name
}

func (g *GuardianClient) fallback(detail string) Verdict {
	decision := DecisionPass
	if !g.failOpen {
		decision = DecisionFail
	}
	reason := fmt.Sprintf("guardian unavailable: %s", detail)
	return Verdict{
		Decision: decision,
		Rule:     nil,
		Reason:   &reason,
		Policy:   "fallback",
	}
}

// Close is a no-op today; exists for API symmetry / future pooling.
func (g *GuardianClient) Close() error { return nil }
