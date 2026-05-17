const PANES: ReadonlyArray<{ title: string; blurb: string }> = [
  {
    title: "Traces",
    blurb:
      "Browse AgentTraceEvent streams emitted by the Python / TypeScript SDKs.",
  },
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
          Observability and policy plane for agentic AI — Phase 5 scaffold.
        </p>
      </header>
      <section style={gridStyle}>
        {PANES.map((p) => (
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
  maxWidth: 960,
  margin: "0 auto",
  padding: "32px 24px",
  color: "#1a1a1a",
};

const headerStyle: React.CSSProperties = {
  borderBottom: "1px solid #e5e5e5",
  paddingBottom: 24,
  marginBottom: 24,
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
