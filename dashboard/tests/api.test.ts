import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchEvents,
  fetchReflection,
  fetchReflections,
  fetchSession,
  fetchSessions,
} from "../src/api.js";

const BASE = "http://127.0.0.1:8089";

/** Install a fake fetch that records calls and returns `body` as JSON. */
function stubFetch(body: unknown, ok = true, status = 200) {
  const calls: string[] = [];
  const fake = vi.fn(async (url: string | URL) => {
    calls.push(String(url));
    return {
      ok,
      status,
      json: async () => body,
    } as Response;
  });
  vi.stubGlobal("fetch", fake);
  return calls;
}

/** Capture full RequestInit (URL + init) per call. */
function stubFetchWithInit(body: unknown, ok = true, status = 200) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fake = vi.fn(async (url: string | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return {
      ok,
      status,
      json: async () => body,
    } as Response;
  });
  vi.stubGlobal("fetch", fake);
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("fetchEvents", () => {
  it("hits /v1/events with no query string when unfiltered", async () => {
    const calls = stubFetch([]);
    await fetchEvents();
    expect(calls).toEqual([`${BASE}/v1/events`]);
  });

  it("encodes every filter into the query string", async () => {
    const calls = stubFetch([]);
    await fetchEvents({
      agent_id: "a",
      session_id: "s1",
      event_type: "POLICY_CHECK",
      limit: 50,
    });
    const url = new URL(calls[0]!);
    expect(url.pathname).toBe("/v1/events");
    expect(url.searchParams.get("agent_id")).toBe("a");
    expect(url.searchParams.get("session_id")).toBe("s1");
    expect(url.searchParams.get("event_type")).toBe("POLICY_CHECK");
    expect(url.searchParams.get("limit")).toBe("50");
  });

  it("omits filters that are not set", async () => {
    const calls = stubFetch([]);
    await fetchEvents({ agent_id: "only-agent" });
    const url = new URL(calls[0]!);
    expect(url.searchParams.get("agent_id")).toBe("only-agent");
    expect(url.searchParams.has("limit")).toBe(false);
    expect(url.searchParams.has("event_type")).toBe(false);
  });

  it("includes limit=0 explicitly (it is a valid value)", async () => {
    const calls = stubFetch([]);
    await fetchEvents({ limit: 0 });
    expect(new URL(calls[0]!).searchParams.get("limit")).toBe("0");
  });

  it("returns the parsed JSON body", async () => {
    stubFetch([{ trace_id: "t1" }]);
    const events = await fetchEvents();
    expect(events).toEqual([{ trace_id: "t1" }]);
  });

  it("throws with the status code on a non-ok response", async () => {
    stubFetch(null, false, 503);
    await expect(fetchEvents()).rejects.toThrow("HTTP 503");
  });
});

describe("fetchSessions", () => {
  it("hits /v1/sessions", async () => {
    const calls = stubFetch([]);
    await fetchSessions();
    expect(calls).toEqual([`${BASE}/v1/sessions`]);
  });
});

describe("fetchSession", () => {
  it("builds a path-encoded session URL", async () => {
    const calls = stubFetch([]);
    await fetchSession("agent/with slash", "s 1");
    expect(calls[0]).toBe(
      `${BASE}/v1/sessions/agent%2Fwith%20slash/s%201`,
    );
  });
});

describe("fetchReflections", () => {
  it("hits /v1/reflections", async () => {
    const calls = stubFetch([]);
    await fetchReflections();
    expect(calls).toEqual([`${BASE}/v1/reflections`]);
  });
});

describe("fetchReflection", () => {
  it("encodes the reflection name into the path", async () => {
    const calls = stubFetch({ name: "x", date: "x", content: "" });
    await fetchReflection("reflection-2026-05-22.md");
    expect(calls[0]).toBe(
      `${BASE}/v1/reflections/reflection-2026-05-22.md`,
    );
  });

  it("propagates a 404 as a thrown error", async () => {
    stubFetch(null, false, 404);
    await expect(
      fetchReflection("reflection-2099-01-01.md"),
    ).rejects.toThrow("HTTP 404");
  });
});

describe("bearer-token resolution (ADR-007)", () => {
  it("omits the Authorization header when VITE_TRUSTLAYER_API_TOKEN is unset", async () => {
    vi.stubEnv("VITE_TRUSTLAYER_API_TOKEN", "");
    const calls = stubFetchWithInit([]);
    await fetchEvents();
    const headers = (calls[0]!.init?.headers ?? undefined) as
      | Record<string, string>
      | undefined;
    expect(headers?.Authorization).toBeUndefined();
  });

  it("sends Authorization: Bearer when VITE_TRUSTLAYER_API_TOKEN is set", async () => {
    vi.stubEnv("VITE_TRUSTLAYER_API_TOKEN", "dash-secret");
    const calls = stubFetchWithInit([]);
    await fetchEvents();
    const headers = calls[0]!.init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer dash-secret");
  });

  it("applies the header to every wrapper (sessions, reflections)", async () => {
    vi.stubEnv("VITE_TRUSTLAYER_API_TOKEN", "dash-secret");
    const calls = stubFetchWithInit([]);
    await fetchSessions();
    await fetchReflections();
    for (const call of calls) {
      const headers = call.init?.headers as Record<string, string>;
      expect(headers.Authorization).toBe("Bearer dash-secret");
    }
  });
});
