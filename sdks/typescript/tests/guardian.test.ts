import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GuardianClient } from "../src/guardian.js";
import { TrustLayerClient } from "../src/client.js";
import { Tracer } from "../src/tracer.js";
import type { AgentTraceEvent } from "../src/schema.js";

function event(overrides: Partial<AgentTraceEvent> = {}): AgentTraceEvent {
  return {
    trace_id: "11111111-1111-4111-8111-111111111111",
    agent_id: "researcher-1",
    session_id: "S1",
    timestamp: "2026-05-16T10:00:00.000Z",
    event_type: "TOOL_CALL",
    cynefin_domain: "COMPLEX",
    payload: { tool_name: "external_llm", tool_args: { prompt: "hi" } },
    metrics: {},
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function captureEmitClient(): {
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

describe("GuardianClient", () => {
  it("posts event + policy_name and returns the parsed verdict", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const fakeFetch = vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return jsonResponse({
        decision: "FAIL",
        rule: "block_external_llm",
        reason: "PII",
        policy: "default",
      });
    }) as unknown as typeof fetch;

    const guardian = new GuardianClient({
      fetch: fakeFetch,
      policyName: "default",
    });
    const verdict = await guardian.check(event());

    expect(verdict).toEqual({
      decision: "FAIL",
      rule: "block_external_llm",
      reason: "PII",
      policy: "default",
    });
    const body = JSON.parse(calls[0]!.init.body as string);
    expect(body.policy_name).toBe("default");
    expect(body.event.agent_id).toBe("researcher-1");
    expect(body.event.payload.tool_name).toBe("external_llm");
  });

  it("explicit policy_name overrides the client default", async () => {
    let captured: { policy_name?: string } = {};
    const fakeFetch = (async (_url: string, init: RequestInit) => {
      captured = JSON.parse(init.body as string);
      return jsonResponse({
        decision: "PASS",
        rule: null,
        reason: null,
        policy: "ad-hoc",
      });
    }) as unknown as typeof fetch;

    const guardian = new GuardianClient({
      fetch: fakeFetch,
      policyName: "default",
    });
    await guardian.check(event(), "ad-hoc");
    expect(captured.policy_name).toBe("ad-hoc");
  });

  it("fail-open returns PASS fallback on transport error", async () => {
    const onError = vi.fn();
    const fakeFetch = (async () => {
      throw new Error("connection refused");
    }) as unknown as typeof fetch;

    const guardian = new GuardianClient({ fetch: fakeFetch, onError });
    const verdict = await guardian.check(event());
    expect(verdict.decision).toBe("PASS");
    expect(verdict.policy).toBe("fallback");
    expect(verdict.reason).toContain("connection refused");
    expect(onError).toHaveBeenCalledOnce();
  });

  it("fail-closed returns FAIL fallback on transport error", async () => {
    const fakeFetch = (async () => {
      throw new Error("connection refused");
    }) as unknown as typeof fetch;

    const guardian = new GuardianClient({
      fetch: fakeFetch,
      failOpen: false,
      onError: () => undefined,
    });
    const verdict = await guardian.check(event());
    expect(verdict.decision).toBe("FAIL");
    expect(verdict.policy).toBe("fallback");
  });

  it("5xx response falls back without throwing", async () => {
    const fakeFetch = (async () =>
      new Response(null, { status: 500 })) as unknown as typeof fetch;
    const guardian = new GuardianClient({ fetch: fakeFetch });
    const verdict = await guardian.check(event());
    expect(verdict.decision).toBe("PASS");
    expect(verdict.policy).toBe("fallback");
    expect(verdict.reason).toContain("HTTP 500");
  });

  it("unexpected decision string triggers fallback", async () => {
    const fakeFetch = (async () =>
      jsonResponse({
        decision: "MAYBE",
        rule: null,
        reason: null,
        policy: "x",
      })) as unknown as typeof fetch;
    const guardian = new GuardianClient({ fetch: fakeFetch });
    const verdict = await guardian.check(event());
    expect(verdict.decision).toBe("PASS");
    expect(verdict.policy).toBe("fallback");
  });

  it("clean PASS verdict round-trips", async () => {
    const fakeFetch = (async () =>
      jsonResponse({
        decision: "PASS",
        rule: "allow_calculator",
        reason: null,
        policy: "default",
      })) as unknown as typeof fetch;
    const guardian = new GuardianClient({ fetch: fakeFetch });
    const verdict = await guardian.check(event());
    expect(verdict).toEqual({
      decision: "PASS",
      rule: "allow_calculator",
      reason: null,
      policy: "default",
    });
  });

  it("attaches Authorization header when apiKey is set", async () => {
    let receivedHeaders: Record<string, string> = {};
    const fakeFetch = (async (_url: string, init: RequestInit) => {
      receivedHeaders = init.headers as Record<string, string>;
      return jsonResponse({
        decision: "PASS",
        rule: null,
        reason: null,
        policy: "p",
      });
    }) as unknown as typeof fetch;
    const guardian = new GuardianClient({ fetch: fakeFetch, apiKey: "secret" });
    await guardian.check(event());
    expect(receivedHeaders["Authorization"]).toBe("Bearer secret");
  });
});

describe("Tracer.check", () => {
  it("emits TOOL_CALL then POLICY_CHECK and returns the verdict", async () => {
    const { client, events } = captureEmitClient();
    const guardianFetch = (async () =>
      jsonResponse({
        decision: "FAIL",
        rule: "block_external_llm",
        reason: "PII",
        policy: "default",
      })) as unknown as typeof fetch;
    const guardian = new GuardianClient({
      fetch: guardianFetch,
      policyName: "default",
    });
    const tracer = new Tracer({ agentId: "a", sessionId: "s", client });

    const verdict = await tracer.check(
      "external_llm",
      { prompt: "hi" },
      { guardian },
    );

    expect(verdict.decision).toBe("FAIL");
    expect(events.map((e) => e.event_type)).toEqual([
      "TOOL_CALL",
      "POLICY_CHECK",
    ]);
    expect(events[0]!.payload).toMatchObject({
      tool_name: "external_llm",
      tool_args: { prompt: "hi" },
    });
    expect(events[1]!.payload).toMatchObject({
      policy_name: "default",
      action: "invoke external_llm",
      result: "FAIL",
      reason: "PII",
    });
  });

  it("PASS verdict records PASS in the POLICY_CHECK event", async () => {
    const { client, events } = captureEmitClient();
    const guardianFetch = (async () =>
      jsonResponse({
        decision: "PASS",
        rule: "allow_calculator",
        reason: null,
        policy: "default",
      })) as unknown as typeof fetch;
    const guardian = new GuardianClient({ fetch: guardianFetch });
    const tracer = new Tracer({ agentId: "a", sessionId: "s", client });

    const verdict = await tracer.check("calculator", { x: 1 }, { guardian });

    expect(verdict.decision).toBe("PASS");
    expect(events[1]!.payload).toMatchObject({ result: "PASS" });
  });

  it("forwards explicit policy_name to the guardian", async () => {
    const { client } = captureEmitClient();
    let captured: { policy_name?: string } = {};
    const guardianFetch = (async (_url: string, init: RequestInit) => {
      captured = JSON.parse(init.body as string);
      return jsonResponse({
        decision: "PASS",
        rule: null,
        reason: null,
        policy: "alt",
      });
    }) as unknown as typeof fetch;
    const guardian = new GuardianClient({
      fetch: guardianFetch,
      policyName: "default",
    });
    const tracer = new Tracer({ agentId: "a", sessionId: "s", client });

    await tracer.check("calc", {}, { guardian, policyName: "alt" });
    expect(captured.policy_name).toBe("alt");
  });
});

describe("GuardianClient bearer-token resolution (ADR-007)", () => {
  const ORIGINAL = process.env.TRUSTLAYER_API_TOKEN;

  beforeEach(() => {
    delete process.env.TRUSTLAYER_API_TOKEN;
  });
  afterEach(() => {
    if (ORIGINAL === undefined) delete process.env.TRUSTLAYER_API_TOKEN;
    else process.env.TRUSTLAYER_API_TOKEN = ORIGINAL;
  });

  async function captureHeaders(opts: {
    apiKey?: string;
  }): Promise<Record<string, string>> {
    let captured: Record<string, string> = {};
    const fakeFetch = (async (_url: string, init: RequestInit) => {
      captured = init.headers as Record<string, string>;
      return jsonResponse({
        decision: "PASS",
        rule: null,
        reason: null,
        policy: "p",
      });
    }) as unknown as typeof fetch;
    const guardian = new GuardianClient({ ...opts, fetch: fakeFetch });
    await guardian.check(event());
    return captured;
  }

  it("falls back to TRUSTLAYER_API_TOKEN env var", async () => {
    process.env.TRUSTLAYER_API_TOKEN = "guard-env";
    const headers = await captureHeaders({});
    expect(headers["Authorization"]).toBe("Bearer guard-env");
  });

  it("explicit apiKey overrides env var", async () => {
    process.env.TRUSTLAYER_API_TOKEN = "guard-env";
    const headers = await captureHeaders({ apiKey: "explicit" });
    expect(headers["Authorization"]).toBe("Bearer explicit");
  });

  it("omits Authorization header when no token is set", async () => {
    const headers = await captureHeaders({});
    expect(headers["Authorization"]).toBeUndefined();
  });
});
