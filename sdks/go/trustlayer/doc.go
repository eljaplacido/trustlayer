// Package trustlayer is the Go reference SDK for the TrustLayer protocol,
// version 0.1. See spec/v0.1/ at the repository root for the normative
// contract; this package implements the wire-format-conformance surface
// (W1–W7 in spec/v0.1/06-conformance.md).
//
// Quick example:
//
//	client, err := trustlayer.NewClient(trustlayer.ClientOptions{
//	    Endpoint: "http://127.0.0.1:8089/v1/events",
//	})
//	if err != nil { panic(err) }
//	defer client.Close()
//
//	guardian, err := trustlayer.NewGuardian(trustlayer.GuardianOptions{})
//	if err != nil { panic(err) }
//	defer guardian.Close()
//
//	tracer := trustlayer.NewTracer(client, "researcher-1", "S1")
//	verdict, err := tracer.Check(ctx, "external_llm",
//	    map[string]any{"prompt": "hi"}, &trustlayer.TracerCheck{
//	        Guardian: guardian, PolicyName: "default",
//	    })
//	// inspect verdict.Decision and decide whether to invoke the tool.
//
// All clients are safe for concurrent use by multiple goroutines.
// Instrumentation never returns a fatal error: transport failures from
// Emit / EmitBatch are returned as plain errors that callers MAY ignore,
// matching the "instrumentation must never take down the host agent"
// working agreement.
package trustlayer
