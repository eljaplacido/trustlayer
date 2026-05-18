import { TracesPane } from "./TracesPane.js";

const PLACEHOLDER_PANES: ReadonlyArray<{ title: string; blurb: string }> = [
  {
    title: "Sessions",
    blurb: "Per-(agent, session) timelines rehydrated from Hermes.",
  },
  {
    title: "Reflections",
    blurb: "Deterministic and LLM-backed structural summaries.",
  },
  {
    title: "Policy",
    blurb:
      "Live cynepic-guardian verdicts: PASS / FAIL / ESCALATE and the rule that fired.",
  },
];

export function App() {
  return (
    <main style={containerStyle}>
      <header style={headerStyle}>
        <h1 style={{ margin: 0 }}>TrustLayer</h1>
        <p style={{ marginTop: 8, opacity: 0.7 }}>
          Observability and policy plane for agentic AI.
        </p>
      </header>

      <section style={{ marginBottom: 24 }}>
        <h2 style={paneHeadingStyle}>Traces</h2>
        <p style={paneBlurbStyle}>
          Live AgentTraceEvent stream from the TrustLayer sidecar
          (<code>GET /v1/events</code>).
        </p>
        <div style={paneBodyStyle}>
          <TracesPane />
        </div>
      </section>

      <section style={gridStyle}>
        {PLACEHOLDER_PANES.map((p) => (
          <article key={p.title} style={cardStyle}>
            <h2 style={{ margin: 0 }}>{p.title}</h2>
            <p style={{ marginTop: 8 }}>{p.blurb}</p>
            <span style={pillStyle}>not wired yet</span>
          </article>
        ))}
      </section>
    </main>
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

const paneHeadingStyle: React.CSSProperties = {
  margin: 0,
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

const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
  gap: 16,
};

const cardStyle: React.CSSProperties = {
  border: "1px solid #e5e5e5",
  borderRadius: 8,
  padding: 16,
  background: "#fafafa",
};

const pillStyle: React.CSSProperties = {
  display: "inline-block",
  marginTop: 12,
  padding: "2px 8px",
  borderRadius: 999,
  background: "#fee",
  color: "#a33",
  fontSize: 12,
};
