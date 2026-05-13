import { describe, expect, it } from "vitest";

import { TrustLayerClient } from "../src/client.js";
import { Tracer } from "../src/tracer.js";
import { wrapTool } from "../src/instrumentation.js";
import { AgentTraceEvent } from "../src/schema.js";

function captureClient(): {
  client: TrustLayerClient;
  events: AgentTraceEvent[];
} {
  const events: AgentTraceEvent[] = [];
  const fakeFetch = (async (_url: string, init: RequestInit) => {
    events.push(JSON.parse(init.body as string) as AgentTraceEvent);
    return new Response(null, { status: 202 });
  }) as unknown as typeof fetch;
  return { client: new TrustLayerClient({ fetch: fakeFetch }), events };
}

describe("Tracer", () => {
  it("emits TOOL_CALL then TOOL_RESULT around toolCall", async () => {
    const { client, events } = captureClient();
    const tracer = new Tracer({ agentId: "a", sessionId: "s", client });

    const result = await tracer.toolCall("calc", { x: 1 }, () => 42);

    expect(result).toBe(42);
    expect(events.map((e) => e.event_type)).toEqual([
      "TOOL_CALL",
      "TOOL_RESULT",
    ]);
    expect(events[0]!.payload).toMatchObject({
      tool_name: "calc",
      tool_args: { x: 1 },
    });
    expect(events[1]!.payload).toMatchObject({
      tool_name: "calc",
      result: 42,
    });
    expect(events[1]!.metrics.latency_ms).toBeTypeOf("number");
  });

  it("records error and rethrows", async () => {
    const { client, events } = captureClient();
    const tracer = new Tracer({ agentId: "a", sessionId: "s", client });

    await expect(
      tracer.toolCall("boom", {}, () => {
        throw new Error("nope");
      }),
    ).rejects.toThrow("nope");

    expect(events.at(-1)!.event_type).toBe("TOOL_RESULT");
    expect(events.at(-1)!.payload).toMatchObject({ tool_name: "boom" });
    expect((events.at(-1)!.payload as { error: string }).error).toContain(
      "nope",
    );
  });

  it("policyCheck emits POLICY_CHECK with result", async () => {
    const { client, events } = captureClient();
    const tracer = new Tracer({ agentId: "a", sessionId: "s", client });

    await tracer.policyCheck("pii", "send_to_llm", "FAIL", "Contains SSN");

    expect(events).toHaveLength(1);
    expect(events[0]!.event_type).toBe("POLICY_CHECK");
    expect(events[0]!.payload).toMatchObject({
      policy_name: "pii",
      result: "FAIL",
    });
  });

  it("default sessionId is unique per tracer", () => {
    const { client } = captureClient();
    const a = new Tracer({ agentId: "x", client });
    const b = new Tracer({ agentId: "x", client });
    expect(a.sessionId).not.toBe(b.sessionId);
  });

  it("wrapTool records args and result", async () => {
    const { client, events } = captureClient();
    const tracer = new Tracer({ agentId: "a", sessionId: "s", client });
    const add = wrapTool(tracer, "add", (x: number, y: number) => x + y);

    await expect(add(2, 3)).resolves.toBe(5);
    expect(events.map((e) => e.event_type)).toEqual([
      "TOOL_CALL",
      "TOOL_RESULT",
    ]);
    expect(
      (events[0]!.payload as { tool_args: { args: unknown[] } }).tool_args.args,
    ).toEqual([2, 3]);
  });
});
