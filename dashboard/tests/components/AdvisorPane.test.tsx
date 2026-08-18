// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AdvisorPane } from "../../src/AdvisorPane.js";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const HEALTH_LOCAL = {
  status: "ok",
  provider: "ollama",
  model: "nemotron-3-nano:30b-a3b-q4_K_M",
  residency: "local",
  available: true,
  guardian_enabled: true,
};

const MODELS = { provider: "ollama", current: "m", models: ["m", "n"] };

/** Route stubbed fetches by URL so a test can pin each endpoint separately. */
function stubFetch(routes: Record<string, unknown>, opts: { chatStatus?: number } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const key = Object.keys(routes).find((k) => url.includes(k));
      if (key === undefined) {
        return { ok: false, status: 404, text: async () => "", json: async () => ({}) };
      }
      const isChat = key.includes("advisor/chat");
      const status = isChat ? (opts.chatStatus ?? 200) : 200;
      return {
        ok: status < 400,
        status,
        text: async () => JSON.stringify(routes[key]),
        json: async () => routes[key],
      };
    }),
  );
}

function reply(overrides: Record<string, unknown> = {}) {
  return {
    provider: "ollama",
    model: "nemotron-3-nano:30b-a3b-q4_K_M",
    residency: "local",
    fell_back: false,
    run: {
      run_id: "r1",
      role: "insight_advisor",
      provider: "ollama",
      model: "nemotron-3-nano:30b-a3b-q4_K_M",
      duration_ms: 1234,
      findings: [],
      ungrounded_rejected: 0,
      narrative: "Nothing notable in this window.",
      evidence_window: { event_count: 12, result_hash: "abc" },
      ...overrides,
    },
  };
}

describe("<AdvisorPane />", () => {
  it("states where inference happens before the operator types anything", async () => {
    stubFetch({ "/health": HEALTH_LOCAL, "/v1/models": MODELS });

    render(<AdvisorPane />);

    expect(await screen.findByText(/local inference/)).toBeInTheDocument();
    expect(screen.getByText(/guardian-checked/)).toBeInTheDocument();
  });

  it("warns when the guardian is off, so an unchecked call is not silent", async () => {
    stubFetch({
      "/health": { ...HEALTH_LOCAL, guardian_enabled: false },
      "/v1/models": MODELS,
    });

    render(<AdvisorPane />);

    expect(
      await screen.findByText(/guardian off — calls are not policy-checked/),
    ).toBeInTheDocument();
  });

  it("shows third-country residency as text, not colour alone", async () => {
    stubFetch({
      "/health": { ...HEALTH_LOCAL, provider: "anthropic", residency: "third_country" },
      "/v1/models": MODELS,
    });

    render(<AdvisorPane />);

    expect(await screen.findByText(/residency: third_country/)).toBeInTheDocument();
  });

  it("disables the input when no provider is configured", async () => {
    stubFetch({
      "/health": { ...HEALTH_LOCAL, provider: "null", model: "none" },
      "/v1/models": MODELS,
    });

    render(<AdvisorPane />);

    expect(await screen.findByText(/No provider is configured/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Ask about these insights/)).toBeDisabled();
  });

  it("answers a question and reports the run's provenance", async () => {
    stubFetch({
      "/health": HEALTH_LOCAL,
      "/v1/models": MODELS,
      "advisor/chat": reply(),
    });
    const user = userEvent.setup();

    render(<AdvisorPane />);
    const input = await screen.findByLabelText(/Ask about these insights/);
    await user.type(input, "what happened?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Nothing notable in this window.")).toBeInTheDocument();
    // Provenance is part of the answer, not a debug detail.
    expect(screen.getByText(/12 events in window/)).toBeInTheDocument();
  });

  it("keyboard-only submission works", async () => {
    stubFetch({
      "/health": HEALTH_LOCAL,
      "/v1/models": MODELS,
      "advisor/chat": reply(),
    });
    const user = userEvent.setup();

    render(<AdvisorPane />);
    await user.tab();
    await user.keyboard("why did the guardian fail?{Enter}");

    expect(await screen.findByText("Nothing notable in this window.")).toBeInTheDocument();
  });

  it("renders a finding with its citations and severity as text", async () => {
    stubFetch({
      "/health": HEALTH_LOCAL,
      "/v1/models": MODELS,
      "advisor/chat": reply({
        narrative: null,
        findings: [
          {
            claim: "external_llm was blocked twice",
            cited_trace_ids: ["11111111-1111-4111-8111-111111111111"],
            confidence: "medium",
            severity: "high",
            human_review_required: true,
            remediation: "Relax rule block_external_llm_for_pii_tools",
          },
        ],
      }),
    });
    const user = userEvent.setup();

    render(<AdvisorPane />);
    await user.type(
      await screen.findByLabelText(/Ask about these insights/),
      "any blocks?",
    );
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("external_llm was blocked twice")).toBeInTheDocument();
    expect(screen.getByText(/severity high/)).toBeInTheDocument();
    expect(screen.getByText(/needs human review/)).toBeInTheDocument();
    expect(
      screen.getByText("Relax rule block_external_llm_for_pii_tools"),
    ).toBeInTheDocument();
  });

  it("states how many findings were suppressed as ungrounded", async () => {
    stubFetch({
      "/health": HEALTH_LOCAL,
      "/v1/models": MODELS,
      "advisor/chat": reply({ ungrounded_rejected: 3 }),
    });
    const user = userEvent.setup();

    render(<AdvisorPane />);
    await user.type(await screen.findByLabelText(/Ask about these insights/), "q");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(
      await screen.findByText(/3 findings suppressed as ungrounded/),
    ).toBeInTheDocument();
  });

  it("names an egress refusal as a policy decision, not a failure", async () => {
    stubFetch(
      {
        "/health": { ...HEALTH_LOCAL, provider: "anthropic", residency: "third_country" },
        "/v1/models": MODELS,
        "advisor/chat": { detail: "refused: this system declares personal_data" },
      },
      { chatStatus: 451 },
    );
    const user = userEvent.setup();

    render(<AdvisorPane />);
    await user.type(await screen.findByLabelText(/Ask about these insights/), "q");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/Refused by egress policy/)).toBeInTheDocument();
    expect(screen.getByText(/personal_data/)).toBeInTheDocument();
  });

  it("says so when agentcenter was unreachable and Ollama answered instead", async () => {
    stubFetch({
      "/health": HEALTH_LOCAL,
      "/v1/models": MODELS,
      "advisor/chat": { ...reply(), fell_back: true },
    });
    const user = userEvent.setup();

    render(<AdvisorPane />);
    await user.type(await screen.findByLabelText(/Ask about these insights/), "q");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/agentcenter was unreachable/)).toBeInTheDocument();
  });

  it("degrades to an explanation when the service is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));

    render(<AdvisorPane />);

    await waitFor(() =>
      expect(screen.getByText(/Evaluator service unreachable/)).toBeInTheDocument(),
    );
    // The deterministic panes must keep working — say so.
    expect(screen.getByText(/Deterministic panes are unaffected/)).toBeInTheDocument();
  });
});
