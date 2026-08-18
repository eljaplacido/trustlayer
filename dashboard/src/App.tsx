import { AdvisorPane } from "./AdvisorPane.js";
import { CompliancePane } from "./CompliancePane.js";
import { MetricsPane } from "./MetricsPane.js";
import { OverviewPane } from "./OverviewPane.js";
import { PolicyPane } from "./PolicyPane.js";
import { ReflectionsPane } from "./ReflectionsPane.js";
import { SessionsPane } from "./SessionsPane.js";
import { TracesPane } from "./TracesPane.js";

export function App() {
  return (
    <main style={containerStyle}>
      <header style={headerStyle}>
        <h1 style={{ margin: 0 }}>TrustLayer</h1>
        <p style={{ marginTop: 8, opacity: 0.7 }}>
          Observability and policy plane for agentic AI — dogfooding
          agentcenter, RCCAEF, and routekit.
        </p>
      </header>

      <Pane
        title="Overview"
        blurb="Real-time counts and policy pass rate across all instrumented agents."
      >
        <OverviewPane />
      </Pane>

      <Pane
        title="Metrics"
        blurb={
          <>
            Prometheus metrics from the Guardian sidecar
            (<code>GET /metrics</code>).
          </>
        }
      >
        <MetricsPane />
      </Pane>

      <Pane
        title="Traces"
        blurb={
          <>
            Live AgentTraceEvent stream from the TrustLayer sidecar
            (<code>GET /v1/events</code>).
          </>
        }
      >
        <TracesPane />
      </Pane>

      <Pane
        title="Sessions"
        blurb={
          <>
            Per-(agent, session) summaries (<code>GET /v1/sessions</code>).
            Click a row to drill into its timeline
            (<code>GET /v1/sessions/:agent/:session</code>).
          </>
        }
      >
        <SessionsPane />
      </Pane>

      <Pane
        title="Reflections"
        blurb={
          <>
            Hermes-generated structural summaries
            (<code>GET /v1/reflections</code>). Generation stays Hermes's
            job; the dashboard lists and renders.
          </>
        }
      >
        <ReflectionsPane />
      </Pane>

      <Pane
        title="Policy"
        blurb={
          <>
            cynepic-guardian verdicts — recent <code>POLICY_CHECK</code>{" "}
            events (<code>GET /v1/events?event_type=POLICY_CHECK</code>).
          </>
        }
      >
        <PolicyPane />
      </Pane>

      <Pane
        title="Compliance"
        blurb={
          <>
            AI system readiness checks. Run{" "}
            <code>compliance-report</code> to populate.
          </>
        }
      >
        <CompliancePane />
      </Pane>

      <Pane
        title="Advisor"
        blurb={
          <>
            Ask your own model about these insights, and ask it to propose
            fixes (ADR-020). Every claim cites the events that support it;
            claims that cannot be grounded in the evidence window are
            suppressed rather than shown.
          </>
        }
      >
        <AdvisorPane />
      </Pane>
    </main>
  );
}

function Pane(props: {
  title: string;
  blurb: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 24 }}>
      <h2 style={{ margin: 0 }}>{props.title}</h2>
      <p style={paneBlurbStyle}>{props.blurb}</p>
      <div style={paneBodyStyle}>{props.children}</div>
    </section>
  );
}

const containerStyle: React.CSSProperties = {
  fontFamily: "system-ui, -apple-system, sans-serif",
  maxWidth: 1080,
  margin: "0 auto",
  padding: "32px 24px",
  color: "#1a1a1a",
};

const headerStyle: React.CSSProperties = {
  borderBottom: "1px solid #e5e5e5",
  paddingBottom: 24,
  marginBottom: 24,
};

const paneBlurbStyle: React.CSSProperties = {
  marginTop: 4,
  marginBottom: 12,
  opacity: 0.7,
  fontSize: 13,
};

const paneBodyStyle: React.CSSProperties = {
  border: "1px solid #e5e5e5",
  borderRadius: 8,
  padding: 16,
  background: "#fafafa",
};
