import { describe, expect, it } from "vitest";

import {
  AgentTraceEvent,
  EventType,
  Metrics,
  PolicyCheckPayload,
  ToolCallPayload,
} from "../src/schema.js";

describe("schema", () => {
  it("parses a fully populated event", () => {
    const raw = {
      trace_id: "11111111-1111-4111-8111-111111111111",
      agent_id: "a",
      session_id: "s",
      timestamp: "2026-05-06T10:00:00.000Z",
      event_type: "TOOL_CALL",
      cynefin_domain: "COMPLEX",
      payload: { tool_name: "search", tool_args: { q: "x" } },
      metrics: { latency_ms: 12.5, cost_usd: 0.0001 },
    };
    const parsed = AgentTraceEvent.parse(raw);
    expect(parsed.event_type).toBe("TOOL_CALL");
    expect(parsed.metrics.latency_ms).toBe(12.5);
  });

  it("applies defaults for cynefin_domain, payload, metrics", () => {
    const parsed = AgentTraceEvent.parse({
      trace_id: "11111111-1111-4111-8111-111111111111",
      agent_id: "a",
      session_id: "s",
      timestamp: "2026-05-06T10:00:00.000Z",
      event_type: "AGENT_START",
    });
    expect(parsed.cynefin_domain).toBe("DISORDER");
    expect(parsed.payload).toEqual({});
    expect(parsed.metrics).toEqual({});
  });

  it("rejects unknown top-level fields", () => {
    expect(() =>
      AgentTraceEvent.parse({
        trace_id: "11111111-1111-4111-8111-111111111111",
        agent_id: "a",
        session_id: "s",
        timestamp: "2026-05-06T10:00:00.000Z",
        event_type: "AGENT_START",
        unexpected: "nope",
      }),
    ).toThrow();
  });

  it("rejects invalid event_type", () => {
    expect(() => EventType.parse("NOT_A_REAL_EVENT")).toThrow();
  });

  it("metrics passthrough preserves extra keys", () => {
    const m = Metrics.parse({ latency_ms: 1, custom: 99 });
    expect((m as Record<string, unknown>).custom).toBe(99);
  });

  it("ToolCallPayload defaults tool_args to empty object", () => {
    const p = ToolCallPayload.parse({ tool_name: "x" });
    expect(p.tool_args).toEqual({});
  });

  it("PolicyCheckPayload validates result enum", () => {
    expect(() =>
      PolicyCheckPayload.parse({
        policy_name: "p",
        action: "a",
        result: "WAT",
      }),
    ).toThrow();
  });
});
