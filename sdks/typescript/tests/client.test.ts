import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TrustLayerClient } from "../src/client.js";
import { AgentTraceEvent } from "../src/schema.js";

function event(overrides: Partial<AgentTraceEvent> = {}): AgentTraceEvent {
  return {
    trace_id: "11111111-1111-4111-8111-111111111111",
    agent_id: "a",
    session_id: "s",
    timestamp: "2026-05-06T10:00:00.000Z",
    event_type: "AGENT_START",
    cynefin_domain: "DISORDER",
    payload: {},
    metrics: {},
    ...overrides,
  };
}

describe("TrustLayerClient", () => {
  it("posts JSON with auth header", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const fakeFetch = vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return new Response(null, { status: 202 });
    }) as unknown as typeof fetch;

    const client = new TrustLayerClient({
      apiKey: "secret",
      fetch: fakeFetch,
    });

    await client.emit(event());

    expect(calls).toHaveLength(1);
    const headers = calls[0]!.init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer secret");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(calls[0]!.init.body as string).agent_id).toBe("a");
  });

  it("emitBatch posts an array", async () => {
    let receivedBody: unknown = null;
    const fakeFetch = (async (_url: string, init: RequestInit) => {
      receivedBody = JSON.parse(init.body as string);
      return new Response(null, { status: 202 });
    }) as unknown as typeof fetch;

    const client = new TrustLayerClient({ fetch: fakeFetch });
    await client.emitBatch([
      event(),
      event({ event_type: "AGENT_END" }),
    ]);

    expect(Array.isArray(receivedBody)).toBe(true);
    expect((receivedBody as AgentTraceEvent[]).length).toBe(2);
  });

  it("swallows non-2xx responses via onError", async () => {
    const onError = vi.fn();
    const fakeFetch = (async () =>
      new Response(null, { status: 500 })) as unknown as typeof fetch;

    const client = new TrustLayerClient({ fetch: fakeFetch, onError });
    await expect(client.emit(event())).resolves.toBeUndefined();
    expect(onError).toHaveBeenCalledOnce();
  });

  it("swallows fetch rejections via onError", async () => {
    const onError = vi.fn();
    const fakeFetch = (async () => {
      throw new Error("network down");
    }) as unknown as typeof fetch;

    const client = new TrustLayerClient({ fetch: fakeFetch, onError });
    await expect(client.emit(event())).resolves.toBeUndefined();
    expect(onError).toHaveBeenCalledOnce();
  });
});

describe("TrustLayerClient bearer-token resolution (ADR-007)", () => {
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
      return new Response(null, { status: 202 });
    }) as unknown as typeof fetch;
    const client = new TrustLayerClient({ ...opts, fetch: fakeFetch });
    await client.emit(event());
    return captured;
  }

  it("falls back to TRUSTLAYER_API_TOKEN env var", async () => {
    process.env.TRUSTLAYER_API_TOKEN = "from-env";
    const headers = await captureHeaders({});
    expect(headers["Authorization"]).toBe("Bearer from-env");
  });

  it("explicit apiKey overrides env var", async () => {
    process.env.TRUSTLAYER_API_TOKEN = "from-env";
    const headers = await captureHeaders({ apiKey: "explicit" });
    expect(headers["Authorization"]).toBe("Bearer explicit");
  });

  it("omits Authorization header when no token is set", async () => {
    const headers = await captureHeaders({});
    expect(headers["Authorization"]).toBeUndefined();
  });
});
