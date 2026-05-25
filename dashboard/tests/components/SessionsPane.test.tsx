// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../../src/api.js", () => ({
  fetchSessions: vi.fn(),
  fetchSession: vi.fn(),
}));

import {
  fetchSession,
  fetchSessions,
  type AgentTraceEvent,
  type SessionSummary,
} from "../../src/api.js";
import { SessionsPane } from "../../src/SessionsPane.js";

const SUMMARY: SessionSummary = {
  agent_id: "researcher-1",
  session_id: "S1",
  event_count: 3,
  first_seen: "2026-05-24T09:59:00.000Z",
  last_seen: "2026-05-24T10:01:00.000Z",
};

const TIMELINE: AgentTraceEvent[] = [
  {
    trace_id: "e1",
    agent_id: "researcher-1",
    session_id: "S1",
    timestamp: "2026-05-24T10:00:00.000Z",
    event_type: "TOOL_CALL",
    payload: { tool_name: "calc" },
  },
];

beforeEach(() => {
  vi.mocked(fetchSessions).mockReset();
  vi.mocked(fetchSession).mockReset();
});
afterEach(() => {
  cleanup();
});

describe("<SessionsPane />", () => {
  it("renders the loading state until the sessions list resolves", () => {
    vi.mocked(fetchSessions).mockReturnValue(
      new Promise<SessionSummary[]>(() => {
        /* never resolves */
      }),
    );
    render(<SessionsPane />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("renders the empty state when /v1/sessions is empty", async () => {
    vi.mocked(fetchSessions).mockResolvedValue([]);
    render(<SessionsPane />);
    expect(await screen.findByText(/No sessions yet/)).toBeInTheDocument();
  });

  it("lists summary rows with the agent + session + event_count visible", async () => {
    vi.mocked(fetchSessions).mockResolvedValue([SUMMARY]);
    render(<SessionsPane />);
    expect(await screen.findByText("researcher-1")).toBeInTheDocument();
    expect(screen.getByText("S1")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("clicking a row drills into /v1/sessions/:agent/:session and shows the timeline", async () => {
    vi.mocked(fetchSessions).mockResolvedValue([SUMMARY]);
    vi.mocked(fetchSession).mockResolvedValue(TIMELINE);
    const user = userEvent.setup();

    render(<SessionsPane />);
    await screen.findByText("researcher-1");

    await user.click(screen.getByText("researcher-1"));

    await waitFor(() => {
      expect(fetchSession).toHaveBeenCalledWith("researcher-1", "S1");
    });
    expect(await screen.findByText("calc")).toBeInTheDocument();
    // The TOOL_CALL <code> appears in the drill-down timeline.
    expect(screen.getByText("TOOL_CALL")).toBeInTheDocument();
  });

  it("surfaces a per-session fetch error in the drill-down panel", async () => {
    vi.mocked(fetchSessions).mockResolvedValue([SUMMARY]);
    vi.mocked(fetchSession).mockRejectedValue(new Error("HTTP 404"));
    const user = userEvent.setup();

    render(<SessionsPane />);
    await screen.findByText("researcher-1");
    await user.click(screen.getByText("researcher-1"));
    expect(await screen.findByText(/HTTP 404/)).toBeInTheDocument();
  });
});
