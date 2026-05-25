// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../src/api.js", () => ({
  fetchEvents: vi.fn(),
}));

import { fetchEvents, type AgentTraceEvent } from "../../src/api.js";
import { PolicyPane } from "../../src/PolicyPane.js";

function checkEvent(
  result: "PASS" | "FAIL" | "ESCALATE",
  overrides: Partial<AgentTraceEvent> = {},
): AgentTraceEvent {
  return {
    trace_id: `t-${result}`,
    agent_id: "researcher-1",
    session_id: "S1",
    timestamp: "2026-05-24T10:00:00.000Z",
    event_type: "POLICY_CHECK",
    payload: {
      result,
      action: "invoke external_llm",
      reason: result === "PASS" ? "" : "blocked",
    },
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(fetchEvents).mockReset();
});
afterEach(() => {
  cleanup();
});

describe("<PolicyPane />", () => {
  it("filters /v1/events on event_type=POLICY_CHECK", async () => {
    vi.mocked(fetchEvents).mockResolvedValue([]);
    render(<PolicyPane />);
    await screen.findByText(/No policy checks yet/);
    expect(fetchEvents).toHaveBeenCalledWith(
      expect.objectContaining({ event_type: "POLICY_CHECK", limit: 50 }),
      expect.any(AbortSignal),
    );
  });

  it("renders the empty state when there are no POLICY_CHECK events", async () => {
    vi.mocked(fetchEvents).mockResolvedValue([]);
    render(<PolicyPane />);
    expect(
      await screen.findByText(/No policy checks yet/),
    ).toBeInTheDocument();
  });

  it("renders a row per verdict with the verdict label visible", async () => {
    vi.mocked(fetchEvents).mockResolvedValue([
      checkEvent("PASS"),
      checkEvent("FAIL"),
      checkEvent("ESCALATE"),
    ]);
    render(<PolicyPane />);
    expect(await screen.findByText("PASS")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText("ESCALATE")).toBeInTheDocument();
    // Action + reason show through to the row too.
    const actions = screen.getAllByText("invoke external_llm");
    expect(actions).toHaveLength(3);
  });

  it("surfaces fetch errors verbatim", async () => {
    vi.mocked(fetchEvents).mockRejectedValue(new Error("HTTP 500"));
    render(<PolicyPane />);
    await waitFor(() => {
      expect(screen.getByText(/HTTP 500/)).toBeInTheDocument();
    });
  });
});
