// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("../../src/api.js", () => ({
  baseUrl: vi.fn(() => "http://guardian.test"),
  apiToken: vi.fn(() => undefined),
}));

import { apiToken } from "../../src/api.js";
import { MetricsPane } from "../../src/MetricsPane.js";

/**
 * A realistic `/metrics` scrape. Kept faithful to what `core-rs/src/metrics.rs`
 * actually exposes — including the HELP/TYPE comment lines, the `{route,status}`
 * label pair, and the evidence gauges — because a fixture that is tidier than
 * the real exposition tests a parser nobody runs.
 */
const SCRAPE = `# HELP trustlayer_events_ingested_total Events accepted by the trace store.
# TYPE trustlayer_events_ingested_total counter
trustlayer_events_ingested_total 42
# TYPE trustlayer_check_total counter
trustlayer_check_total{decision="PASS"} 90
trustlayer_check_total{decision="FAIL"} 7
trustlayer_check_total{decision="ESCALATE"} 3
# TYPE trustlayer_requests_total counter
trustlayer_requests_total{route="/v1/events",status="200"} 100
trustlayer_requests_total{route="/v1/events",status="429"} 25
trustlayer_requests_total{route="/v1/check",status="200"} 60
# TYPE trustlayer_check_duration_seconds histogram
trustlayer_check_duration_seconds_bucket{le="0.005"} 80
trustlayer_check_duration_seconds_bucket{le="0.01"} 95
trustlayer_check_duration_seconds_bucket{le="+Inf"} 100
# TYPE trustlayer_retention_live_events gauge
trustlayer_retention_live_events 1200
trustlayer_retention_floor_blocked_total 4
`;

function mockScrape(body: string, ok = true, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    text: async () => body,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.mocked(apiToken).mockReturnValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("<MetricsPane />", () => {
  it("scrapes /metrics on the configured sidecar", async () => {
    const fetchMock = mockScrape(SCRAPE);
    render(<MetricsPane />);
    await screen.findByText("Events Ingested");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://guardian.test/metrics",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("renders the loading state before the first scrape resolves", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<MetricsPane />);
    expect(screen.getByText(/loading metrics/)).toBeInTheDocument();
  });

  it("surfaces a non-2xx scrape as an error rather than an empty dashboard", async () => {
    mockScrape("", false, 503);
    render(<MetricsPane />);
    expect(await screen.findByText("HTTP 503")).toBeInTheDocument();
  });

  it("parses counters and labelled series into the KPI row", async () => {
    mockScrape(SCRAPE);
    render(<MetricsPane />);

    // Ingest counter, and PASS/FAIL split out of the {decision} label.
    expect((await screen.findByText("Events Ingested")).previousSibling).toHaveTextContent("42");
    expect(screen.getByText("Policy PASS").previousSibling).toHaveTextContent("90");
    expect(screen.getByText("Policy FAIL").previousSibling).toHaveTextContent("7");
  });

  it("sums requests per route across status codes", async () => {
    mockScrape(SCRAPE);
    render(<MetricsPane />);
    await screen.findByText("Requests by Route");

    // /v1/events served 100 × 200 and 25 × 429. The bar must read 125, not 25:
    // assigning instead of summing kept only the last status seen, so the bars
    // silently disagreed with the total above them.
    const eventsRoute = screen.getByText("/v1/events");
    expect(eventsRoute.parentElement).toHaveTextContent("125");
    expect(screen.getByText("/v1/check").parentElement).toHaveTextContent("60");

    // Total spans every {route,status} sample: 100 + 25 + 60.
    expect(screen.getByText("Total Requests").previousSibling).toHaveTextContent("185");
  });

  it("ignores HELP/TYPE comment lines", async () => {
    mockScrape(SCRAPE);
    render(<MetricsPane />);
    await screen.findByText("Events Ingested");

    // A comment parsed as a sample would surface its name as a route bar.
    expect(screen.queryByText(/HELP/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^#/)).not.toBeInTheDocument();
  });

  it("renders the latency histogram from _bucket samples", async () => {
    mockScrape(SCRAPE);
    render(<MetricsPane />);

    expect(await screen.findByText("Check Latency Distribution")).toBeInTheDocument();
    // `le="+Inf"` must not crash the bucket maths that parseFloat()s the label.
    expect(screen.getByTitle("<=0.005s: 80")).toBeInTheDocument();
  });

  it("omits the histogram section when the scrape carries no buckets", async () => {
    mockScrape("trustlayer_events_ingested_total 1\n");
    render(<MetricsPane />);
    await screen.findByText("Events Ingested");

    expect(screen.queryByText("Check Latency Distribution")).not.toBeInTheDocument();
  });

  it("sends the bearer token when one is configured", async () => {
    vi.mocked(apiToken).mockReturnValue("s3cret");
    const fetchMock = mockScrape(SCRAPE);
    render(<MetricsPane />);
    await screen.findByText("Events Ingested");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://guardian.test/metrics",
      expect.objectContaining({ headers: { Authorization: "Bearer s3cret" } }),
    );
  });

  it("omits the Authorization header when no token is configured", async () => {
    const fetchMock = mockScrape(SCRAPE);
    render(<MetricsPane />);
    await screen.findByText("Events Ingested");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://guardian.test/metrics",
      expect.objectContaining({ headers: {} }),
    );
  });
});
