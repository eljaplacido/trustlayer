// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

// Mock the api module *before* the pane is imported.
vi.mock("../../src/api.js", () => ({
  fetchEvents: vi.fn(),
}));

import { fetchEvents, type AgentTraceEvent } from "../../src/api.js";
import { TracesPane } from "../../src/TracesPane.js";

function event(overrides: Partial<AgentTraceEvent> = {}): AgentTraceEvent {
  return {
    trace_id: "11111111-1111-4111-8111-111111111111",
    agent_id: "researcher-1",
    session_id: "S1",
    timestamp: "2026-05-24T10:00:00.000Z",
    event_type: "TOOL_CALL",
    payload: { tool_name: "calc" },
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(fetchEvents).mockReset();
});
afterEach(() => {
  cleanup();
});

describe("<TracesPane />", () => {
  it("renders the loading state while the first fetch is in flight", () => {
    vi.mocked(fetchEvents).mockReturnValue(
      new Promise<AgentTraceEvent[]>(() => {
        /* never resolves */
      }),
    );
    render(<TracesPane />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("renders the empty state when the sidecar returns no events", async () => {
    vi.mocked(fetchEvents).mockResolvedValue([]);
    render(<TracesPane />);
    expect(await screen.findByText(/No events yet/)).toBeInTheDocument();
  });

  it("renders one row per event with the tool name in the payload-hint column", async () => {
    vi.mocked(fetchEvents).mockResolvedValue([
      event({ trace_id: "a", payload: { tool_name: "calc" } }),
      event({
        trace_id: "b",
        event_type: "POLICY_CHECK",
        payload: { tool_name: "external_llm" },
      }),
    ]);
    render(<TracesPane />);
    expect(await screen.findByText("calc")).toBeInTheDocument();
    expect(screen.getByText("external_llm")).toBeInTheDocument();
    expect(screen.getByText("TOOL_CALL")).toBeInTheDocument();
    expect(screen.getByText("POLICY_CHECK")).toBeInTheDocument();
  });

  it("renders the error state when the fetch rejects", async () => {
    vi.mocked(fetchEvents).mockRejectedValue(new Error("HTTP 503"));
    render(<TracesPane />);
    await waitFor(() => {
      expect(
        screen.getByText(/Could not reach the TrustLayer sidecar/),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(/HTTP 503/)).toBeInTheDocument();
  });

  it("requests /v1/events with the limit=50 filter on first mount", async () => {
    vi.mocked(fetchEvents).mockResolvedValue([]);
    render(<TracesPane />);
    await screen.findByText(/No events yet/);
    expect(fetchEvents).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 50 }),
      expect.any(AbortSignal),
    );
  });
});
