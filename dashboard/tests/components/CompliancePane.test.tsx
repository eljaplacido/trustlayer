// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { CompliancePane } from "../../src/CompliancePane.js";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("<CompliancePane />", () => {
  it("renders a useful empty state for an empty report", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ systems: [], overall_summary: {} }),
      }),
    );

    render(<CompliancePane />);

    expect(await screen.findByText(/No systems registered/)).toBeInTheDocument();
  });

  it("renders system readiness and check status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          generated_at: "2026-07-18T00:00:00Z",
          systems: [
            {
              system_id: "demo",
              system_name: "Demo",
              summary: { readiness_score_percent: 90 },
              checks: [
                {
                  check_id: "registry",
                  check_title: "System Registry",
                  status: "PASS",
                  details: "Registered",
                  priority: "critical",
                },
              ],
            },
          ],
          overall_summary: {
            overall_readiness_percent: 90,
            total_systems: 1,
            total_passed: 1,
            total_failed: 0,
            total_gaps: 0,
          },
        }),
      }),
    );

    render(<CompliancePane />);

    expect(await screen.findByText("Demo")).toBeInTheDocument();
    expect(screen.getByText("System Registry")).toBeInTheDocument();
    expect(screen.getByText("PASS")).toBeInTheDocument();
  });

  it("surfaces a failed report request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));

    render(<CompliancePane />);

    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 404");
  });
});
