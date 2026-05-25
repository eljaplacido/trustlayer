package trustlayer

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// DefaultIngestEndpoint is the loopback URL the reference Rust sidecar
// listens on. Override via ClientOptions.Endpoint.
const DefaultIngestEndpoint = "http://127.0.0.1:8089/v1/events"

// ClientOptions configures the TrustLayer ingest client.
type ClientOptions struct {
	// Endpoint is the full URL to POST /v1/events on. Empty = default.
	Endpoint string
	// APIKey is the bearer token (ADR-007). Empty falls back to
	// TRUSTLAYER_API_TOKEN; if that is also empty, no Authorization
	// header is sent.
	APIKey string
	// HTTPClient lets callers inject a *http.Client (for tests, timeouts,
	// or transport tuning). nil installs a fresh client with a 5s timeout.
	HTTPClient *http.Client
}

// TrustLayerClient is a goroutine-safe ingest client.
type TrustLayerClient struct {
	endpoint string
	apiKey   string
	http     *http.Client
}

// NewClient constructs a TrustLayerClient. The constructor itself does
// no I/O; the first Emit / EmitBatch call hits the wire.
func NewClient(opts ClientOptions) (*TrustLayerClient, error) {
	endpoint := opts.Endpoint
	if endpoint == "" {
		endpoint = DefaultIngestEndpoint
	}
	httpClient := opts.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 5 * time.Second}
	}
	return &TrustLayerClient{
		endpoint: endpoint,
		apiKey:   resolveAPIToken(opts.APIKey),
		http:     httpClient,
	}, nil
}

// Endpoint returns the URL this client posts to. Useful for tests.
func (c *TrustLayerClient) Endpoint() string { return c.endpoint }

// APIKey returns the (possibly empty) resolved bearer token. Useful for tests.
func (c *TrustLayerClient) APIKey() string { return c.apiKey }

// Emit ships one event. Transport-layer errors are returned for callers
// who want to log them; they MUST NOT propagate into agent control flow.
func (c *TrustLayerClient) Emit(ctx context.Context, event AgentTraceEvent) error {
	body, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("trustlayer: marshal event: %w", err)
	}
	return c.send(ctx, body)
}

// EmitBatch ships a JSON array of events in one POST. Empty input is a
// no-op (returns nil immediately, no request).
func (c *TrustLayerClient) EmitBatch(ctx context.Context, events []AgentTraceEvent) error {
	if len(events) == 0 {
		return nil
	}
	body, err := json.Marshal(events)
	if err != nil {
		return fmt.Errorf("trustlayer: marshal batch: %w", err)
	}
	return c.send(ctx, body)
}

func (c *TrustLayerClient) send(ctx context.Context, body []byte) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("trustlayer: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("trustlayer: emit: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		// Drain a small slice of the body so the server-side log line is
		// retrievable from the returned error, then ignore the rest.
		preview, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("trustlayer: HTTP %d: %s", resp.StatusCode, bytes.TrimSpace(preview))
	}
	return nil
}

// Close is a no-op today (no pooled resources to release beyond the
// http.Client). It exists for API symmetry with the Python SDK and so
// callers can adopt `defer client.Close()` ergonomics now and stay
// safe when we add pooling later.
func (c *TrustLayerClient) Close() error { return nil }
